using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO.Compression;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace DClaw.LocalHelper;

internal sealed record HelperConfig(
    string ServerWebSocketUri,
    string DeviceId,
    string? DeviceToken,
    string? PairingCode,
    string DisplayName,
    string RunnerVersion = "1.0.0",
    string ProtocolVersion = "1");

internal sealed class Program
{
    private static async Task<int> Main(string[] args)
    {
        if (args.Length != 1 || !File.Exists(args[0])) return 2;
        using var singleInstance = new Mutex(
            true,
            "Local\\DClaw.LocalHelper.v1",
            out var ownsMutex);
        if (!ownsMutex) return 0;
        var configPath = Path.GetFullPath(args[0]);
        var config = JsonSerializer.Deserialize<HelperConfig>(
            await File.ReadAllTextAsync(configPath), JsonOptions.Default);
        if (config is null) return 2;
        var runtime = new HelperRuntime(configPath, config);
        await runtime.RunAsync(CancellationToken.None);
        return 0;
    }
}

internal sealed class HelperRuntime
{
    private readonly string _configPath;
    private HelperConfig _config;
    private readonly string _root;
    private readonly HttpClient _http = new(new HttpClientHandler { AllowAutoRedirect = true });
    private readonly ConcurrentDictionary<string, Process> _processes = new();
    private readonly ConcurrentDictionary<string, byte> _cancelled = new();
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private readonly SemaphoreSlim _statusLock = new(1, 1);
    private ClientWebSocket? _socket;
    private volatile bool _connected;

    public HelperRuntime(string configPath, HelperConfig config)
    {
        _configPath = configPath;
        _config = config;
        _root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "DClawLocalTool");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(Path.Combine(_root, "Capabilities"));
        Directory.CreateDirectory(Path.Combine(_root, "Tasks"));
        Directory.CreateDirectory(Path.Combine(_root, "Outbox"));
    }

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        using var heartbeatCancellation = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken);
        var heartbeat = WriteHeartbeatAsync(heartbeatCancellation.Token);
        var delay = TimeSpan.FromSeconds(1);
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    await ConnectAndReceiveAsync(cancellationToken);
                    delay = TimeSpan.FromSeconds(1);
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    return;
                }
                catch
                {
                    await Task.Delay(delay, cancellationToken);
                    delay = TimeSpan.FromSeconds(Math.Min(delay.TotalSeconds * 2, 30));
                }
            }
        }
        finally
        {
            heartbeatCancellation.Cancel();
            try { await heartbeat; } catch (OperationCanceledException) { }
            await DeleteStatusIfOwnedAsync();
        }
    }

    private async Task ConnectAndReceiveAsync(CancellationToken cancellationToken)
    {
        using var socket = new ClientWebSocket();
        _socket = socket;
        var uri = BuildConnectionUri();
        await socket.ConnectAsync(uri, cancellationToken);
        _connected = true;
        await WriteStatusAsync(cancellationToken);
        try
        {
            await FlushOutboxAsync(cancellationToken);
            var buffer = new byte[1024 * 1024];
            while (socket.State == WebSocketState.Open)
            {
                using var content = new MemoryStream();
                WebSocketReceiveResult received;
                do
                {
                    received = await socket.ReceiveAsync(buffer, cancellationToken);
                    if (received.MessageType == WebSocketMessageType.Close) return;
                    content.Write(buffer, 0, received.Count);
                } while (!received.EndOfMessage);
                using var document = JsonDocument.Parse(content.ToArray());
                await HandleMessageAsync(document.RootElement, cancellationToken);
            }
        }
        finally
        {
            _connected = false;
            await WriteStatusAsync(CancellationToken.None);
        }
    }

    private async Task WriteHeartbeatAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(10));
        do
        {
            await WriteStatusAsync(cancellationToken);
        } while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task WriteStatusAsync(CancellationToken cancellationToken)
    {
        await _statusLock.WaitAsync(cancellationToken);
        try
        {
            var statusPath = Path.Combine(_root, "helper-status.json");
            var temporary = statusPath + ".tmp";
            var status = new
            {
                pid = Environment.ProcessId,
                connected = _connected,
                deviceId = _config.DeviceId,
                heartbeatUnixSeconds = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
            };
            await File.WriteAllTextAsync(
                temporary,
                JsonSerializer.Serialize(status, JsonOptions.Default),
                cancellationToken);
            File.Move(temporary, statusPath, true);
        }
        finally
        {
            _statusLock.Release();
        }
    }

    private async Task DeleteStatusIfOwnedAsync()
    {
        var statusPath = Path.Combine(_root, "helper-status.json");
        await _statusLock.WaitAsync();
        try
        {
            if (!File.Exists(statusPath)) return;
            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(statusPath));
            if (document.RootElement.GetProperty("pid").GetInt32() == Environment.ProcessId)
                File.Delete(statusPath);
        }
        finally
        {
            _statusLock.Release();
        }
    }

    private Uri BuildConnectionUri()
    {
        var separator = _config.ServerWebSocketUri.Contains('?') ? "&" : "?";
        var query = new Dictionary<string, string?>
        {
            ["device_id"] = _config.DeviceId,
            ["device_token"] = _config.DeviceToken,
            ["pairing_code"] = _config.DeviceToken is null ? _config.PairingCode : null,
            ["display_name"] = _config.DisplayName,
            ["runner_version"] = _config.RunnerVersion,
            ["protocol_version"] = _config.ProtocolVersion,
        };
        var encoded = string.Join("&", query.Where(item => !string.IsNullOrWhiteSpace(item.Value))
            .Select(item => $"{Uri.EscapeDataString(item.Key)}={Uri.EscapeDataString(item.Value!)}"));
        return new Uri(_config.ServerWebSocketUri + separator + encoded);
    }

    private async Task HandleMessageAsync(JsonElement message, CancellationToken cancellationToken)
    {
        var type = message.GetProperty("type").GetString();
        switch (type)
        {
            case "connection.ready":
                await SaveIdentityAsync(message, cancellationToken);
                await ReportCapabilitiesAsync(cancellationToken);
                break;
            case "runtime.prepare":
                await PrepareRuntimeAsync(message.GetProperty("capability_package"), cancellationToken);
                await ReportCapabilitiesAsync(cancellationToken);
                break;
            case "task.start":
                _ = ExecuteTaskAsync(message, false, cancellationToken);
                break;
            case "task.continue":
                _ = ExecuteTaskAsync(message, true, cancellationToken);
                break;
            case "task.cancel":
                CancelTask(message.GetProperty("task_id").GetString()!);
                break;
        }
    }

    private async Task SaveIdentityAsync(JsonElement message, CancellationToken cancellationToken)
    {
        if (!message.TryGetProperty("device_token", out var tokenElement)) return;
        var token = tokenElement.GetString();
        if (string.IsNullOrWhiteSpace(token)) return;
        _config = _config with
        {
            DeviceId = message.GetProperty("device_id").GetString()!,
            DeviceToken = token,
            PairingCode = null,
        };
        var temporary = _configPath + ".tmp";
        await File.WriteAllTextAsync(
            temporary,
            JsonSerializer.Serialize(_config, JsonOptions.Default),
            cancellationToken);
        File.Move(temporary, _configPath, true);
    }

    private async Task PrepareRuntimeAsync(JsonElement package, CancellationToken cancellationToken)
    {
        var descriptor = package.GetProperty("descriptor");
        var artifact = descriptor.GetProperty("artifact");
        var packageId = descriptor.GetProperty("package_id").GetString()!;
        var packageVersion = descriptor.GetProperty("package_version").GetString()!;
        var expectedHash = artifact.GetProperty("sha256").GetString()!;
        var expectedSize = artifact.GetProperty("size_bytes").GetInt64();
        var packageRoot = Path.Combine(_root, "Capabilities", SafeName(packageId), SafeName(packageVersion));
        if (File.Exists(Path.Combine(packageRoot, "descriptor.json"))) return;
        var temporaryRoot = packageRoot + ".installing-" + Guid.NewGuid().ToString("N");
        var archivePath = temporaryRoot + ".zip";
        Directory.CreateDirectory(temporaryRoot);
        try
        {
            using var response = await _http.GetAsync(
                artifact.GetProperty("url").GetString(),
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            response.EnsureSuccessStatusCode();
            await using (var output = File.Create(archivePath))
            await using (var input = await response.Content.ReadAsStreamAsync(cancellationToken))
            {
                await input.CopyToAsync(output, cancellationToken);
            }
            var info = new FileInfo(archivePath);
            if (info.Length != expectedSize) throw new InvalidDataException("package size mismatch");
            await using (var stream = File.OpenRead(archivePath))
            {
                var actual = Convert.ToHexString(await SHA256.HashDataAsync(stream, cancellationToken)).ToLowerInvariant();
                if (!CryptographicOperations.FixedTimeEquals(
                    Encoding.ASCII.GetBytes(actual), Encoding.ASCII.GetBytes(expectedHash)))
                    throw new InvalidDataException("package digest mismatch");
            }
            ExtractSafely(archivePath, temporaryRoot);
            await VerifySchemaFilesAsync(
                temporaryRoot,
                descriptor.GetProperty("schemas"),
                cancellationToken);
            await File.WriteAllTextAsync(
                Path.Combine(temporaryRoot, "descriptor.json"),
                descriptor.GetRawText(), cancellationToken);
            Directory.CreateDirectory(Path.GetDirectoryName(packageRoot)!);
            Directory.Move(temporaryRoot, packageRoot);
        }
        finally
        {
            if (File.Exists(archivePath)) File.Delete(archivePath);
            if (Directory.Exists(temporaryRoot)) Directory.Delete(temporaryRoot, true);
        }
    }

    private static void ExtractSafely(string archivePath, string targetRoot)
    {
        var fullRoot = Path.GetFullPath(targetRoot) + Path.DirectorySeparatorChar;
        using var archive = ZipFile.OpenRead(archivePath);
        foreach (var entry in archive.Entries)
        {
            var destination = Path.GetFullPath(Path.Combine(targetRoot, entry.FullName));
            if (!destination.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("package path escapes install root");
            if (string.IsNullOrEmpty(entry.Name))
            {
                Directory.CreateDirectory(destination);
                continue;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            entry.ExtractToFile(destination, true);
        }
    }

    private static async Task VerifySchemaFilesAsync(
        string packageRoot,
        JsonElement schemas,
        CancellationToken cancellationToken)
    {
        var fullRoot = Path.GetFullPath(packageRoot) + Path.DirectorySeparatorChar;
        foreach (var schema in schemas.EnumerateObject())
        {
            var declaration = schema.Value;
            var path = Path.GetFullPath(Path.Combine(
                packageRoot,
                declaration.GetProperty("path").GetString()!));
            if (!path.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("schema path escapes package root");
            await using var stream = File.OpenRead(path);
            var actual = Convert.ToHexString(
                await SHA256.HashDataAsync(stream, cancellationToken)).ToLowerInvariant();
            var expected = declaration.GetProperty("sha256").GetString()!;
            if (!CryptographicOperations.FixedTimeEquals(
                Encoding.ASCII.GetBytes(actual), Encoding.ASCII.GetBytes(expected)))
                throw new InvalidDataException($"{schema.Name} schema digest mismatch");
            var installedDocument = JsonNode.Parse(
                await File.ReadAllTextAsync(path, cancellationToken));
            var signedDocument = JsonNode.Parse(
                declaration.GetProperty("document").GetRawText());
            if (!JsonNode.DeepEquals(installedDocument, signedDocument))
                throw new InvalidDataException($"{schema.Name} schema content mismatch");
        }
    }

    private async Task ExecuteTaskAsync(
        JsonElement message,
        bool continuation,
        CancellationToken cancellationToken)
    {
        var task = continuation ? message : message.GetProperty("task");
        var taskId = task.GetProperty("task_id").GetString()!;
        try
        {
            var agentName = continuation
                ? ReadAgentName(taskId)
                : task.GetProperty("task_root_name").GetString()!;
            var taskRoot = FindOrCreateTaskRoot(agentName, taskId);
            var capabilityId = continuation
                ? ReadTaskCapability(taskId)
                : task.GetProperty("capability_id").GetString()!;
            var descriptorPath = FindDescriptor(capabilityId);
            using var descriptorDocument = JsonDocument.Parse(await File.ReadAllTextAsync(descriptorPath, cancellationToken));
            var descriptor = descriptorDocument.RootElement;
            if (!continuation)
            {
                await File.WriteAllTextAsync(Path.Combine(taskRoot, "input.json"), task.GetProperty("input").GetRawText(), cancellationToken);
                await File.WriteAllTextAsync(Path.Combine(taskRoot, "capability.id"), capabilityId, cancellationToken);
                await File.WriteAllTextAsync(Path.Combine(taskRoot, "agent.name"), agentName, cancellationToken);
                if (message.TryGetProperty("runtime_credentials", out var credentials))
                    await File.WriteAllTextAsync(Path.Combine(taskRoot, ".credentials.json"), credentials.GetRawText(), cancellationToken);
            }
            else
            {
                await File.WriteAllTextAsync(Path.Combine(taskRoot, "continuation.json"), message.GetProperty("input").GetRawText(), cancellationToken);
            }
            await SendEventAsync(taskId, "started", new JsonObject(), cancellationToken);
            var packageRoot = Path.GetDirectoryName(descriptorPath)!;
            var entrypoint = descriptor.GetProperty("entrypoint");
            var limits = descriptor.GetProperty("limits");
            var maxRuntime = TimeSpan.FromSeconds(
                limits.GetProperty("max_runtime_seconds").GetInt32());
            var maxMemoryBytes = checked(
                limits.GetProperty("max_memory_mib").GetInt64() * 1024 * 1024);
            var maxDiskBytes = checked(
                limits.GetProperty("max_disk_mib").GetInt64() * 1024 * 1024);
            var maxOutputBytes = limits.GetProperty("max_output_bytes").GetInt64();
            var executable = Path.GetFullPath(Path.Combine(packageRoot, entrypoint.GetProperty("executable").GetString()!));
            if (!executable.StartsWith(Path.GetFullPath(packageRoot) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("entrypoint escapes package root");
            var start = new ProcessStartInfo(executable)
            {
                WorkingDirectory = taskRoot,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            foreach (var argument in entrypoint.GetProperty("arguments").EnumerateArray())
                start.ArgumentList.Add(argument.GetString()!);
            start.ArgumentList.Add("--task-root");
            start.ArgumentList.Add(taskRoot);
            if (continuation) start.ArgumentList.Add("--continue");
            using var process = Process.Start(start) ?? throw new InvalidOperationException("capability did not start");
            _processes[taskId] = process;
            if (_cancelled.ContainsKey(taskId) && !process.HasExited)
                process.Kill(true);
            var standardOutput = process.StandardOutput.ReadToEndAsync(cancellationToken);
            var standardError = process.StandardError.ReadToEndAsync(cancellationToken);
            var resourceMonitor = MonitorResourcesAsync(
                process,
                taskRoot,
                maxRuntime,
                maxMemoryBytes,
                maxDiskBytes,
                cancellationToken);
            await Task.WhenAll(
                process.WaitForExitAsync(cancellationToken),
                standardOutput,
                standardError,
                resourceMonitor);
            await File.WriteAllTextAsync(
                Path.Combine(taskRoot, "res", "stdout.log"),
                standardOutput.Result,
                cancellationToken);
            await File.WriteAllTextAsync(
                Path.Combine(taskRoot, "res", "stderr.log"),
                standardError.Result,
                cancellationToken);
            _processes.TryRemove(taskId, out _);
            DeleteCredentialFile(taskRoot);
            if (_cancelled.TryRemove(taskId, out _))
            {
                await SendEventAsync(taskId, "cancelled", new JsonObject(), cancellationToken);
            }
            else if (resourceMonitor.Result is string resourceError)
            {
                await SendEventAsync(taskId, "failed", new JsonObject
                {
                    ["code"] = resourceError,
                }, cancellationToken);
            }
            else if (OutputSize(taskRoot) > maxOutputBytes)
            {
                await SendEventAsync(taskId, "failed", new JsonObject
                {
                    ["code"] = "RUNNER.OUTPUT_LIMIT_EXCEEDED",
                }, cancellationToken);
            }
            else if (process.ExitCode == 0)
            {
                await SendFileEventAsync(taskId, "completed", Path.Combine(taskRoot, "result.json"), cancellationToken);
            }
            else if (process.ExitCode == 10)
            {
                await SendFileEventAsync(taskId, "checkpoint", Path.Combine(taskRoot, "checkpoint.json"), cancellationToken);
            }
            else
            {
                var error = new JsonObject
                {
                    ["code"] = "CAPABILITY.PROCESS_FAILED",
                    ["exit_code"] = process.ExitCode,
                };
                await SendEventAsync(taskId, "failed", error, cancellationToken);
            }
        }
        catch (Exception exception)
        {
            var error = new JsonObject
            {
                ["code"] = "RUNNER.EXECUTION_FAILED",
                ["message"] = exception.GetType().Name,
            };
            await SendEventAsync(taskId, "failed", error, cancellationToken);
        }
    }

    private void CancelTask(string taskId)
    {
        _cancelled[taskId] = 1;
        if (_processes.TryRemove(taskId, out var process) && !process.HasExited)
        {
            process.Kill(true);
        }
    }

    private static async Task<string?> MonitorResourcesAsync(
        Process process,
        string taskRoot,
        TimeSpan maxRuntime,
        long maxMemoryBytes,
        long maxDiskBytes,
        CancellationToken cancellationToken)
    {
        var started = Stopwatch.StartNew();
        while (!process.HasExited)
        {
            string? violation = null;
            try
            {
                process.Refresh();
            }
            catch (InvalidOperationException)
            {
                return null;
            }
            if (started.Elapsed > maxRuntime)
                violation = "RUNNER.TIME_LIMIT_EXCEEDED";
            else if (process.WorkingSet64 > maxMemoryBytes)
                violation = "RUNNER.MEMORY_LIMIT_EXCEEDED";
            else if (DirectorySize(taskRoot) > maxDiskBytes)
                violation = "RUNNER.DISK_LIMIT_EXCEEDED";
            if (violation is not null)
            {
                process.Kill(true);
                return violation;
            }
            await Task.Delay(TimeSpan.FromMilliseconds(500), cancellationToken);
        }
        return null;
    }

    private static long DirectorySize(string root) => Directory
        .EnumerateFiles(root, "*", SearchOption.AllDirectories)
        .Sum(path => new FileInfo(path).Length);

    private static long OutputSize(string taskRoot) => Directory
        .EnumerateFiles(taskRoot, "*", SearchOption.TopDirectoryOnly)
        .Where(path => !Path.GetFileName(path).StartsWith('.'))
        .Where(path => !new[]
        {
            "input.json", "continuation.json", "result.json", "checkpoint.json",
            "capability.id", "agent.name",
        }.Contains(Path.GetFileName(path), StringComparer.OrdinalIgnoreCase))
        .Sum(path => new FileInfo(path).Length);

    private async Task SendFileEventAsync(
        string taskId,
        string eventType,
        string path,
        CancellationToken cancellationToken)
    {
        var payload = File.Exists(path)
            ? JsonNode.Parse(await File.ReadAllTextAsync(path, cancellationToken)) as JsonObject
            : null;
        await SendEventAsync(taskId, eventType, payload ?? new JsonObject(), cancellationToken);
    }

    private async Task SendEventAsync(
        string taskId,
        string eventType,
        JsonObject payload,
        CancellationToken cancellationToken)
    {
        var message = new JsonObject
        {
            ["type"] = "task.event",
            ["task_id"] = taskId,
            ["sequence"] = NextSequence(taskId),
            ["event_type"] = eventType,
            ["payload"] = payload,
        };
        var outboxPath = Path.Combine(
            _root,
            "Outbox",
            $"{SafeName(taskId)}-{message["sequence"]!.GetValue<int>():D10}.json");
        await File.WriteAllTextAsync(
            outboxPath,
            message.ToJsonString(JsonOptions.Default),
            cancellationToken);
        if (await SendAsync(message, cancellationToken)) File.Delete(outboxPath);
    }

    private async Task ReportCapabilitiesAsync(CancellationToken cancellationToken)
    {
        var capabilities = new JsonArray();
        var root = Path.Combine(_root, "Capabilities");
        foreach (var descriptorPath in Directory.EnumerateFiles(root, "descriptor.json", SearchOption.AllDirectories))
        {
            using var descriptor = JsonDocument.Parse(await File.ReadAllTextAsync(descriptorPath, cancellationToken));
            var item = descriptor.RootElement;
            capabilities.Add(new JsonObject
            {
                ["capability_id"] = item.GetProperty("capability_id").GetString(),
                ["version"] = item.GetProperty("contract_version").GetString(),
                ["package_id"] = item.GetProperty("package_id").GetString(),
                ["package_version"] = item.GetProperty("package_version").GetString(),
            });
        }
        await SendAsync(new JsonObject
        {
            ["type"] = "capabilities.report",
            ["capabilities"] = capabilities,
        }, cancellationToken);
    }

    private async Task<bool> SendAsync(JsonObject message, CancellationToken cancellationToken)
    {
        var socket = _socket;
        if (socket is null || socket.State != WebSocketState.Open) return false;
        var bytes = Encoding.UTF8.GetBytes(message.ToJsonString(JsonOptions.Default));
        await _sendLock.WaitAsync(cancellationToken);
        try
        {
            await socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken);
            return true;
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private async Task FlushOutboxAsync(CancellationToken cancellationToken)
    {
        foreach (var path in Directory.EnumerateFiles(
            Path.Combine(_root, "Outbox"), "*.json").OrderBy(item => item))
        {
            var message = JsonNode.Parse(
                await File.ReadAllTextAsync(path, cancellationToken)) as JsonObject;
            if (message is null) continue;
            if (!await SendAsync(message, cancellationToken)) return;
            File.Delete(path);
        }
    }

    private int NextSequence(string taskId)
    {
        var taskRoot = FindTaskRoot(taskId);
        var path = Path.Combine(taskRoot, ".sequence");
        var current = File.Exists(path) && int.TryParse(File.ReadAllText(path), out var parsed)
            ? parsed
            : 0;
        var next = checked(current + 1);
        File.WriteAllText(path, next.ToString());
        return next;
    }

    private string FindDescriptor(string capabilityId)
    {
        foreach (var path in Directory.EnumerateFiles(
            Path.Combine(_root, "Capabilities"), "descriptor.json", SearchOption.AllDirectories))
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            if (document.RootElement.GetProperty("capability_id").GetString() == capabilityId)
                return path;
        }
        throw new FileNotFoundException("capability is not installed", capabilityId);
    }

    private string FindOrCreateTaskRoot(string agentName, string taskId)
    {
        var path = Path.Combine(_root, "Tasks", SafeName(agentName), SafeName(taskId));
        Directory.CreateDirectory(path);
        Directory.CreateDirectory(Path.Combine(path, "res"));
        return path;
    }

    private string FindTaskRoot(string taskId) => Directory.EnumerateDirectories(
        Path.Combine(_root, "Tasks"), SafeName(taskId), SearchOption.AllDirectories).First();

    private string ReadTaskCapability(string taskId) => File.ReadAllText(Path.Combine(FindTaskRoot(taskId), "capability.id"));
    private string ReadAgentName(string taskId) => File.ReadAllText(Path.Combine(FindTaskRoot(taskId), "agent.name"));
    private static void DeleteCredentialFile(string taskRoot)
    {
        var path = Path.Combine(taskRoot, ".credentials.json");
        if (File.Exists(path)) File.Delete(path);
    }

    private static string SafeName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars().ToHashSet();
        var normalized = new string(value.Select(character => invalid.Contains(character) ? '_' : character).ToArray()).Trim();
        return string.IsNullOrWhiteSpace(normalized) ? "unnamed" : normalized[..Math.Min(normalized.Length, 80)];
    }
}

internal static class JsonOptions
{
    public static readonly JsonSerializerOptions Default = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };
}
