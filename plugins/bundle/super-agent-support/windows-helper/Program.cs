using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO.Compression;
using System.Net.WebSockets;
using System.Runtime.InteropServices;
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
    string DisplayName);

internal static class HelperMetadata
{
    internal const string Version = "1.4.2";
    internal const string ProtocolVersion = "2";
}

internal static class HelperStorage
{
    internal static string Root => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DClawLocalTool");
}

internal sealed class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length != 1 || !File.Exists(args[0])) return 2;
        using var singleInstance = new Mutex(
            true,
            "Local\\DClaw.LocalHelper.v1",
            out var ownsMutex);
        if (!ownsMutex) return 0;
        var configPath = Path.GetFullPath(args[0]);
        var config = JsonSerializer.Deserialize<HelperConfig>(
            File.ReadAllText(configPath), JsonOptions.Default);
        if (config is null) return 2;
        using var cancellation = new CancellationTokenSource();
        var runtime = new HelperRuntime(configPath, config);
        var runtimeTask = Task.Run(() => runtime.RunAsync(cancellation.Token));
        LocalAssistantUi.Run(HelperStorage.Root, () => runtime.Connected);
        cancellation.Cancel();
        try
        {
            runtimeTask.GetAwaiter().GetResult();
        }
        catch (OperationCanceledException)
        {
            // Normal application shutdown.
        }
        return 0;
    }
}

internal sealed class HelperRuntime
{
    private readonly string _configPath;
    private HelperConfig _config;
    private readonly string _root;
    private readonly HttpClient _http = new(new HttpClientHandler { AllowAutoRedirect = true });
    private readonly HttpClient _uploadHttp = new(new HttpClientHandler { AllowAutoRedirect = false });
    private readonly ConcurrentDictionary<string, Process> _processes = new();
    private readonly ConcurrentDictionary<string, byte> _cancelled = new();
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private readonly SemaphoreSlim _statusLock = new(1, 1);
    private ClientWebSocket? _socket;
    private volatile bool _connected;

    internal bool Connected => _connected;

    public HelperRuntime(string configPath, HelperConfig config)
    {
        _configPath = configPath;
        _config = config;
        _root = HelperStorage.Root;
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(Path.Combine(_root, "Capabilities"));
        Directory.CreateDirectory(Path.Combine(_root, "Components"));
        Directory.CreateDirectory(Path.Combine(_root, "Tasks"));
        Directory.CreateDirectory(Path.Combine(_root, "Outbox"));
        Directory.CreateDirectory(Path.Combine(_root, "LocalFileRefs"));
        Directory.CreateDirectory(Path.Combine(_root, "ManagedArtifacts"));
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
            ["runner_version"] = HelperMetadata.Version,
            ["protocol_version"] = HelperMetadata.ProtocolVersion,
            ["platform"] = "windows-x64",
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
                var components = message.TryGetProperty("public_components", out var declaredComponents)
                    ? declaredComponents
                    : default;
                if (components.ValueKind == JsonValueKind.Array)
                {
                    foreach (var component in components.EnumerateArray())
                        await PreparePublicComponentAsync(component, cancellationToken);
                }
                await PrepareRuntimeAsync(
                    message.GetProperty("capability_package"),
                    components,
                    cancellationToken);
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
            case "file.select":
                await SelectFilesAsync(message, cancellationToken);
                break;
            case "file.upload":
                await UploadFileAsync(message, cancellationToken);
                break;
            case "managed_artifacts.list":
                await ListManagedArtifactsAsync(message, cancellationToken);
                break;
            case "managed_artifact.action":
                await ManageArtifactAsync(message, cancellationToken);
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

    private async Task PreparePublicComponentAsync(
        JsonElement envelope,
        CancellationToken cancellationToken)
    {
        var descriptor = envelope.GetProperty("descriptor");
        var componentId = descriptor.GetProperty("component_id").GetString()!;
        var componentVersion = descriptor.GetProperty("component_version").GetString()!;
        if (descriptor.GetProperty("platform").GetString() != "windows-x64"
            || descriptor.GetProperty("status").GetString() != "available")
            throw new InvalidDataException("public Component is unavailable for this platform");

        var canonicalPayload = Convert.FromBase64String(
            envelope.GetProperty("canonical_payload").GetString()!);
        var canonicalNode = JsonNode.Parse(canonicalPayload);
        var descriptorNode = JsonNode.Parse(descriptor.GetRawText());
        if (canonicalNode is null || descriptorNode is null
            || !JsonNode.DeepEquals(canonicalNode, descriptorNode))
            throw new InvalidDataException("public Component canonical payload mismatch");
        using (var verifier = ECDsa.Create())
        {
            verifier.ImportSubjectPublicKeyInfo(
                Convert.FromBase64String(envelope.GetProperty("signer_public_key").GetString()!),
                out _);
            if (!verifier.VerifyData(
                canonicalPayload,
                Convert.FromBase64String(envelope.GetProperty("signature").GetString()!),
                HashAlgorithmName.SHA256,
                DSASignatureFormat.Rfc3279DerSequence))
                throw new InvalidDataException("public Component signature is invalid");
        }

        var componentRoot = Path.Combine(
            _root,
            "Components",
            SafeName(componentId),
            SafeName(componentVersion));
        if (File.Exists(Path.Combine(componentRoot, "descriptor.json"))) return;
        var artifact = descriptor.GetProperty("artifact");
        var expectedHash = artifact.GetProperty("sha256").GetString()!;
        var expectedSize = artifact.GetProperty("size_bytes").GetInt64();
        var maximumUnpackedSize = artifact.TryGetProperty("unpacked_size_bytes", out var unpacked)
            ? unpacked.GetInt64()
            : 8L * 1024 * 1024 * 1024;
        var temporaryRoot = componentRoot + ".installing-" + Guid.NewGuid().ToString("N");
        var archivePath = temporaryRoot + ".zip";
        Directory.CreateDirectory(temporaryRoot);
        try
        {
            await DownloadAndVerifyAsync(
                artifact.GetProperty("url").GetString()!,
                archivePath,
                expectedSize,
                expectedHash,
                cancellationToken);
            ExtractSafely(archivePath, temporaryRoot, maximumUnpackedSize);
            await File.WriteAllTextAsync(
                Path.Combine(temporaryRoot, "descriptor.json"),
                descriptor.GetRawText(),
                cancellationToken);
            await File.WriteAllTextAsync(
                Path.Combine(temporaryRoot, "signature.json"),
                JsonSerializer.Serialize(new
                {
                    signerId = envelope.GetProperty("signer_id").GetString(),
                    signature = envelope.GetProperty("signature").GetString(),
                }, JsonOptions.Default),
                cancellationToken);
            Directory.CreateDirectory(Path.GetDirectoryName(componentRoot)!);
            Directory.Move(temporaryRoot, componentRoot);
        }
        finally
        {
            if (File.Exists(archivePath)) File.Delete(archivePath);
            if (Directory.Exists(temporaryRoot)) Directory.Delete(temporaryRoot, true);
        }
    }

    private async Task PrepareRuntimeAsync(
        JsonElement package,
        JsonElement components,
        CancellationToken cancellationToken)
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
            await DownloadAndVerifyAsync(
                artifact.GetProperty("url").GetString()!,
                archivePath,
                expectedSize,
                expectedHash,
                cancellationToken);
            ExtractSafely(archivePath, temporaryRoot);
            await VerifySchemaFilesAsync(
                temporaryRoot,
                descriptor.GetProperty("schemas"),
                cancellationToken);
            await File.WriteAllTextAsync(
                Path.Combine(temporaryRoot, "descriptor.json"),
                descriptor.GetRawText(), cancellationToken);
            if (components.ValueKind == JsonValueKind.Array)
                await File.WriteAllTextAsync(
                    Path.Combine(temporaryRoot, "public-components.json"),
                    components.GetRawText(),
                    cancellationToken);
            Directory.CreateDirectory(Path.GetDirectoryName(packageRoot)!);
            Directory.Move(temporaryRoot, packageRoot);
        }
        finally
        {
            if (File.Exists(archivePath)) File.Delete(archivePath);
            if (Directory.Exists(temporaryRoot)) Directory.Delete(temporaryRoot, true);
        }
    }

    private async Task DownloadAndVerifyAsync(
        string url,
        string destination,
        long expectedSize,
        string expectedHash,
        CancellationToken cancellationToken)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var artifactUri)
            || artifactUri.Scheme != Uri.UriSchemeHttps)
            throw new InvalidDataException("artifact URL must use HTTPS");
        using var response = await _http.GetAsync(
            artifactUri,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long contentLength
            && contentLength != expectedSize)
            throw new InvalidDataException("artifact size mismatch");
        await using (var output = File.Create(destination))
        await using (var input = await response.Content.ReadAsStreamAsync(cancellationToken))
        {
            await input.CopyToAsync(output, cancellationToken);
        }
        if (new FileInfo(destination).Length != expectedSize)
            throw new InvalidDataException("artifact size mismatch");
        await using var stream = File.OpenRead(destination);
        var actual = Convert.ToHexString(
            await SHA256.HashDataAsync(stream, cancellationToken)).ToLowerInvariant();
        if (!CryptographicOperations.FixedTimeEquals(
            Encoding.ASCII.GetBytes(actual), Encoding.ASCII.GetBytes(expectedHash)))
            throw new InvalidDataException("artifact digest mismatch");
    }

    private static void ExtractSafely(
        string archivePath,
        string targetRoot,
        long maximumUnpackedSize = 8L * 1024 * 1024 * 1024)
    {
        var fullRoot = Path.GetFullPath(targetRoot) + Path.DirectorySeparatorChar;
        using var archive = ZipFile.OpenRead(archivePath);
        long unpackedSize = 0;
        foreach (var entry in archive.Entries)
        {
            unpackedSize = checked(unpackedSize + entry.Length);
            if (unpackedSize > maximumUnpackedSize)
                throw new InvalidDataException("archive expands beyond declared limit");
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

    private async Task SelectFilesAsync(
        JsonElement message,
        CancellationToken cancellationToken)
    {
        var requestId = message.GetProperty("request_id").GetString()!;
        try
        {
            if (!OperatingSystem.IsWindows())
                throw new LocalFileException("FILE_SELECTOR.UNSUPPORTED");
            var selector = message.GetProperty("selector");
            var paths = NativeFileDialog.SelectFiles(selector);
            if (paths is null)
            {
                await SendDurableResponseAsync(new JsonObject
                {
                    ["type"] = "file.select.result",
                    ["request_id"] = requestId,
                    ["status"] = "cancelled",
                    ["files"] = new JsonArray(),
                }, requestId, cancellationToken);
                return;
            }
            var minimum = OptionalInt(selector, "min_files", 1);
            var maximum = OptionalInt(selector, "max_files", 1);
            if (paths.Count < minimum || paths.Count > maximum)
                throw new LocalFileException("FILE_SELECTOR.FILE_COUNT_EXCEEDED");
            var maxFileSize = OptionalLong(selector, "max_file_size_bytes", 536_870_912);
            var maxTotalSize = OptionalLong(selector, "max_total_size_bytes", 536_870_912);
            long total = 0;
            var files = new JsonArray();
            foreach (var selectedPath in paths)
            {
                var fullPath = Path.GetFullPath(selectedPath);
                var info = new FileInfo(fullPath);
                if (!info.Exists) throw new LocalFileException("LOCAL_FILE_REF.FILE_MISSING");
                if (info.Length > maxFileSize)
                    throw new LocalFileException("FILE_SELECTOR.FILE_TOO_LARGE");
                total = checked(total + info.Length);
                if (total > maxTotalSize)
                    throw new LocalFileException("FILE_SELECTOR.FILE_TOO_LARGE");
                ValidateSelectedType(info, selector);
                files.Add(await RegisterLocalFileAsync(
                    fullPath,
                    message.GetProperty("scope"),
                    message.GetProperty("interaction_id").GetString()!,
                    cancellationToken));
            }
            await SendDurableResponseAsync(new JsonObject
            {
                ["type"] = "file.select.result",
                ["request_id"] = requestId,
                ["status"] = "selected",
                ["files"] = files,
            }, requestId, cancellationToken);
        }
        catch (LocalFileException exception)
        {
            await SendFileErrorAsync(
                "file.select.result", requestId, exception.Code, cancellationToken,
                includeFiles: true);
        }
        catch
        {
            await SendFileErrorAsync(
                "file.select.result", requestId, "LOCAL_FILE_REF.RESOLVE_FAILED",
                cancellationToken, includeFiles: true);
        }
    }

    private async Task UploadFileAsync(
        JsonElement message,
        CancellationToken cancellationToken)
    {
        var requestId = message.GetProperty("request_id").GetString()!;
        try
        {
            var localFileRef = message.GetProperty("local_file_ref").GetString()!;
            var path = await ResolveLocalFileAsync(
                localFileRef, message.GetProperty("scope"), cancellationToken);
            var upload = message.GetProperty("upload");
            var url = new Uri(upload.GetProperty("url").GetString()!);
            if (url.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(url.UserInfo))
                throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
            var allowedDomains = upload.GetProperty("allowed_domains")
                .EnumerateArray().Select(item => item.GetString()).ToHashSet(
                    StringComparer.OrdinalIgnoreCase);
            if (!allowedDomains.Contains(url.Host))
                throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
            var info = new FileInfo(path);
            var maxSize = OptionalLong(upload, "max_size_bytes", info.Length);
            if (info.Length > maxSize)
                throw new LocalFileException("FILE_SELECTOR.FILE_TOO_LARGE");
            var method = upload.TryGetProperty("method", out var methodValue)
                ? methodValue.GetString() : "PUT";
            if (method is not ("PUT" or "POST"))
                throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
            using var request = new HttpRequestMessage(new HttpMethod(method), url);
            await using var input = File.OpenRead(path);
            request.Content = new StreamContent(input);
            request.Content.Headers.ContentLength = info.Length;
            if (upload.TryGetProperty("headers", out var headers))
            {
                foreach (var header in headers.EnumerateObject())
                {
                    if (!IsAllowedUploadHeader(header.Name))
                        throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
                    if (!request.Headers.TryAddWithoutValidation(
                        header.Name, header.Value.GetString()))
                        request.Content.Headers.TryAddWithoutValidation(
                            header.Name, header.Value.GetString());
                }
            }
            using var response = await _uploadHttp.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (!response.IsSuccessStatusCode)
                throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
            await using var digestInput = File.OpenRead(path);
            var digest = Convert.ToHexString(
                await SHA256.HashDataAsync(digestInput, cancellationToken))
                .ToLowerInvariant();
            await SendDurableResponseAsync(new JsonObject
            {
                ["type"] = "file.upload.result",
                ["request_id"] = requestId,
                ["status"] = "uploaded",
                ["size_bytes"] = info.Length,
                ["sha256"] = digest,
            }, requestId, cancellationToken);
        }
        catch (LocalFileException exception)
        {
            await SendFileErrorAsync(
                "file.upload.result", requestId, exception.Code, cancellationToken);
        }
        catch
        {
            await SendFileErrorAsync(
                "file.upload.result", requestId, "LOCAL_FILE_REF.RESOLVE_FAILED",
                cancellationToken);
        }
    }

    private async Task<JsonObject> RegisterLocalFileAsync(
        string path,
        JsonElement scope,
        string interactionId,
        CancellationToken cancellationToken)
    {
        var info = new FileInfo(path);
        var localFileRef = "lfr_" + Convert.ToHexString(
            RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
        await using var input = File.OpenRead(path);
        var digest = Convert.ToHexString(
            await SHA256.HashDataAsync(input, cancellationToken)).ToLowerInvariant();
        var lastModified = new DateTimeOffset(info.LastWriteTimeUtc).ToUnixTimeMilliseconds();
        var record = new JsonObject
        {
            ["local_file_ref"] = localFileRef,
            ["canonical_path"] = path,
            ["display_name"] = info.Name,
            ["mime_type"] = MimeType(info.Extension),
            ["size_bytes"] = info.Length,
            ["last_modified_ms"] = lastModified,
            ["sha256"] = digest,
            ["scope"] = JsonNode.Parse(scope.GetRawText()),
            ["interaction_id"] = interactionId,
            ["expires_at"] = DateTimeOffset.UtcNow.AddHours(1).ToUnixTimeSeconds(),
            ["revoked"] = false,
        };
        await WriteJsonAtomicallyAsync(
            LocalFileRecordPath(localFileRef), record, cancellationToken);
        return new JsonObject
        {
            ["local_file_ref"] = localFileRef,
            ["display_name"] = info.Name,
            ["mime_type"] = MimeType(info.Extension),
            ["size_bytes"] = info.Length,
            ["device_id"] = _config.DeviceId,
            ["last_modified_ms"] = lastModified,
        };
    }

    private async Task<string> ResolveLocalFileAsync(
        string localFileRef,
        JsonElement scope,
        CancellationToken cancellationToken)
    {
        var recordPath = LocalFileRecordPath(localFileRef);
        if (!File.Exists(recordPath))
            throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
        var record = JsonNode.Parse(
            await File.ReadAllTextAsync(recordPath, cancellationToken)) as JsonObject;
        if (record is null) throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
        if (record["revoked"]?.GetValue<bool>() == true)
            throw new LocalFileException("LOCAL_FILE_REF.REVOKED");
        if (record["expires_at"]!.GetValue<long>() <= DateTimeOffset.UtcNow.ToUnixTimeSeconds())
            throw new LocalFileException("LOCAL_FILE_REF.EXPIRED");
        var expectedScope = JsonNode.Parse(scope.GetRawText());
        if (!JsonNode.DeepEquals(record["scope"], expectedScope))
            throw new LocalFileException("LOCAL_FILE_REF.SCOPE_MISMATCH");
        var path = record["canonical_path"]!.GetValue<string>();
        if (!File.Exists(path)) throw new LocalFileException("LOCAL_FILE_REF.FILE_MISSING");
        var info = new FileInfo(path);
        var modified = new DateTimeOffset(info.LastWriteTimeUtc).ToUnixTimeMilliseconds();
        if (info.Length != record["size_bytes"]!.GetValue<long>()
            || modified != record["last_modified_ms"]!.GetValue<long>())
            throw new LocalFileException("LOCAL_FILE_REF.FILE_CHANGED");
        await using var input = File.OpenRead(path);
        var digest = Convert.ToHexString(
            await SHA256.HashDataAsync(input, cancellationToken)).ToLowerInvariant();
        if (!CryptographicOperations.FixedTimeEquals(
            Encoding.ASCII.GetBytes(digest),
            Encoding.ASCII.GetBytes(record["sha256"]!.GetValue<string>())))
            throw new LocalFileException("LOCAL_FILE_REF.FILE_CHANGED");
        return path;
    }

    private static void ValidateSelectedType(FileInfo info, JsonElement selector)
    {
        if (selector.TryGetProperty("accept_extensions", out var extensions)
            && extensions.GetArrayLength() > 0
            && !extensions.EnumerateArray().Any(item => string.Equals(
                item.GetString(), info.Extension, StringComparison.OrdinalIgnoreCase)))
            throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
        if (selector.TryGetProperty("accept_mime_types", out var mimeTypes)
            && mimeTypes.GetArrayLength() > 0
            && !mimeTypes.EnumerateArray().Any(item => MimeTypeMatches(
                MimeType(info.Extension), item.GetString())))
            throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
    }

    private static bool MimeTypeMatches(string actual, string? accepted) =>
        !string.IsNullOrWhiteSpace(accepted)
        && (string.Equals(actual, accepted, StringComparison.OrdinalIgnoreCase)
            || (accepted.EndsWith("/*", StringComparison.Ordinal)
                && actual.StartsWith(
                    accepted[..^1], StringComparison.OrdinalIgnoreCase)));

    private static bool IsAllowedUploadHeader(string name) =>
        name.Equals("content-type", StringComparison.OrdinalIgnoreCase)
        || name.Equals("content-md5", StringComparison.OrdinalIgnoreCase)
        || name.StartsWith("x-amz-", StringComparison.OrdinalIgnoreCase)
        || name.StartsWith("x-oss-", StringComparison.OrdinalIgnoreCase)
        || name.StartsWith("x-goog-", StringComparison.OrdinalIgnoreCase);

    private static int OptionalInt(JsonElement value, string name, int fallback) =>
        value.TryGetProperty(name, out var property) ? property.GetInt32() : fallback;

    private static long OptionalLong(JsonElement value, string name, long fallback) =>
        value.TryGetProperty(name, out var property) ? property.GetInt64() : fallback;

    private async Task ExecuteTaskAsync(
        JsonElement message,
        bool continuation,
        CancellationToken cancellationToken)
    {
        var task = continuation ? message : message.GetProperty("task");
        var taskId = task.GetProperty("task_id").GetString()!;
        string? taskRoot = null;
        string? agentName = null;
        string? capabilityId = null;
        try
        {
            agentName = continuation
                ? ReadAgentName(taskId)
                : task.GetProperty("task_root_name").GetString()!;
            taskRoot = FindOrCreateTaskRoot(agentName, taskId);
            capabilityId = continuation
                ? ReadTaskCapability(taskId)
                : task.GetProperty("capability_id").GetString()!;
            var descriptorPath = FindDescriptor(capabilityId);
            using var descriptorDocument = JsonDocument.Parse(await File.ReadAllTextAsync(descriptorPath, cancellationToken));
            var descriptor = descriptorDocument.RootElement;
            if (!continuation)
            {
                var taskInput = JsonNode.Parse(task.GetProperty("input").GetRawText())
                    as JsonObject ?? throw new InvalidDataException("task input is invalid");
                if (task.TryGetProperty("local_file_bindings", out var bindings)
                    && bindings.ValueKind == JsonValueKind.Object
                    && bindings.EnumerateObject().Any())
                {
                    await StageLocalFileBindingsAsync(
                        taskRoot,
                        taskInput,
                        bindings,
                        task.GetProperty("scope"),
                        cancellationToken);
                }
                await File.WriteAllTextAsync(
                    Path.Combine(taskRoot, "input.json"),
                    taskInput.ToJsonString(JsonOptions.Default),
                    cancellationToken);
                await File.WriteAllTextAsync(Path.Combine(taskRoot, "capability.id"), capabilityId, cancellationToken);
                await File.WriteAllTextAsync(Path.Combine(taskRoot, "agent.name"), agentName, cancellationToken);
                if (message.TryGetProperty("runtime_credentials", out var credentials))
                    await File.WriteAllTextAsync(Path.Combine(taskRoot, ".credentials.json"), credentials.GetRawText(), cancellationToken);
            }
            else
            {
                var continuationInput = JsonNode.Parse(message.GetProperty("input").GetRawText())
                    as JsonObject ?? throw new InvalidDataException("continuation input is invalid");
                if (message.TryGetProperty("local_file_bindings", out var bindings)
                    && bindings.ValueKind == JsonValueKind.Object
                    && bindings.EnumerateObject().Any())
                {
                    await StageLocalFileBindingsAsync(
                        taskRoot,
                        continuationInput,
                        bindings,
                        message.GetProperty("scope"),
                        cancellationToken);
                }
                await File.WriteAllTextAsync(
                    Path.Combine(taskRoot, "continuation.json"),
                    continuationInput.ToJsonString(JsonOptions.Default),
                    cancellationToken);
            }
            await TaskHistory.TryWriteAsync(
                taskRoot,
                taskId,
                agentName,
                capabilityId,
                "running",
                null,
                cancellationToken);
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
            var components = await LoadPublicComponentsAsync(packageRoot, cancellationToken);
            var executable = ResolveEntrypoint(packageRoot, entrypoint, components);
            var start = new ProcessStartInfo(executable)
            {
                WorkingDirectory = taskRoot,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            ApplyComponentEnvironment(start, descriptor, components);
            foreach (var argument in entrypoint.GetProperty("arguments").EnumerateArray())
                start.ArgumentList.Add(
                    ExpandArgument(argument.GetString()!, packageRoot, taskRoot));
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
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "cancelled", null, cancellationToken);
                await SendEventAsync(taskId, "cancelled", new JsonObject(), cancellationToken);
            }
            else if (resourceMonitor.Result is string resourceError)
            {
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "failed", resourceError, cancellationToken);
                await SendEventAsync(taskId, "failed", new JsonObject
                {
                    ["code"] = resourceError,
                }, cancellationToken);
            }
            else if (OutputSize(taskRoot) > maxOutputBytes)
            {
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "failed", "RUNNER.OUTPUT_LIMIT_EXCEEDED", cancellationToken);
                await SendEventAsync(taskId, "failed", new JsonObject
                {
                    ["code"] = "RUNNER.OUTPUT_LIMIT_EXCEEDED",
                }, cancellationToken);
            }
            else if (process.ExitCode == 0)
            {
                await RegisterManagedArtifactsAsync(taskId, taskRoot, cancellationToken);
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "completed", null, cancellationToken);
                await SendFileEventAsync(taskId, "completed", Path.Combine(taskRoot, "result.json"), cancellationToken);
            }
            else if (process.ExitCode == 10)
            {
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "waiting", null, cancellationToken);
                await SendFileEventAsync(taskId, "checkpoint", Path.Combine(taskRoot, "checkpoint.json"), cancellationToken);
            }
            else
            {
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "failed", "CAPABILITY.PROCESS_FAILED", cancellationToken);
                var error = new JsonObject
                {
                    ["code"] = "CAPABILITY.PROCESS_FAILED",
                    ["exit_code"] = process.ExitCode,
                };
                await SendEventAsync(taskId, "failed", error, cancellationToken);
            }
        }
        catch (LocalFileException exception)
        {
            if (taskRoot is not null && agentName is not null && capabilityId is not null)
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "failed", exception.Code, cancellationToken);
            await SendEventAsync(taskId, "failed", new JsonObject
            {
                ["code"] = exception.Code,
            }, cancellationToken);
        }
        catch (Exception exception)
        {
            if (taskRoot is not null && agentName is not null && capabilityId is not null)
                await TaskHistory.TryWriteAsync(
                    taskRoot, taskId, agentName, capabilityId,
                    "failed", "RUNNER.EXECUTION_FAILED", cancellationToken);
            var error = new JsonObject
            {
                ["code"] = "RUNNER.EXECUTION_FAILED",
                ["message"] = exception.GetType().Name,
            };
            await SendEventAsync(taskId, "failed", error, cancellationToken);
        }
    }

    private async Task StageLocalFileBindingsAsync(
        string taskRoot,
        JsonObject taskInput,
        JsonElement bindings,
        JsonElement scope,
        CancellationToken cancellationToken)
    {
        foreach (var binding in bindings.EnumerateObject())
        {
            var safeBinding = SafeName(binding.Name);
            if (!string.Equals(safeBinding, binding.Name, StringComparison.Ordinal))
                throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
            if (taskInput.ContainsKey(binding.Name))
                throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
            var declaration = binding.Value;
            if (declaration.GetProperty("access").GetString() != "read")
                throw new LocalFileException("FILE_SELECTOR.PERMISSION_DENIED");
            var reference = declaration.GetProperty("local_file_ref").GetString()!;
            var source = await ResolveLocalFileAsync(reference, scope, cancellationToken);
            var displayName = Path.GetFileName(source);
            var destinationRoot = Path.Combine(taskRoot, "res", "bindings", safeBinding);
            Directory.CreateDirectory(destinationRoot);
            var destination = Path.GetFullPath(Path.Combine(destinationRoot, displayName));
            var fullDestinationRoot = Path.GetFullPath(destinationRoot)
                + Path.DirectorySeparatorChar;
            if (!destination.StartsWith(fullDestinationRoot, StringComparison.OrdinalIgnoreCase))
                throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
            File.Copy(source, destination, true);
            File.SetAttributes(destination, File.GetAttributes(destination) | FileAttributes.ReadOnly);
            taskInput[binding.Name] = Path.GetRelativePath(taskRoot, destination)
                .Replace(Path.DirectorySeparatorChar, '/');
        }
    }

    private async Task RegisterManagedArtifactsAsync(
        string taskId,
        string taskRoot,
        CancellationToken cancellationToken)
    {
        foreach (var output in TaskHistory.DiscoverOutputs(taskRoot))
        {
            var source = output.FullPath;
            var artifactId = "artifact_" + Convert.ToHexString(
                RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
            var artifactRoot = Path.Combine(_root, "ManagedArtifacts", artifactId);
            Directory.CreateDirectory(artifactRoot);
            var destination = Path.Combine(artifactRoot, Path.GetFileName(source));
            File.Copy(source, destination, false);
            var info = new FileInfo(destination);
            var record = new JsonObject
            {
                ["artifact_id"] = artifactId,
                ["task_id"] = taskId,
                ["display_name"] = info.Name,
                ["mime_type"] = MimeType(info.Extension),
                ["size_bytes"] = info.Length,
                ["created_at"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                ["canonical_path"] = destination,
            };
            await WriteJsonAtomicallyAsync(
                Path.Combine(artifactRoot, "artifact.json"), record, cancellationToken);
        }
    }

    private async Task ListManagedArtifactsAsync(
        JsonElement message,
        CancellationToken cancellationToken)
    {
        var requestId = message.GetProperty("request_id").GetString()!;
        var artifacts = new JsonArray();
        foreach (var recordPath in Directory.EnumerateFiles(
            Path.Combine(_root, "ManagedArtifacts"), "artifact.json",
            SearchOption.AllDirectories))
        {
            var record = JsonNode.Parse(
                await File.ReadAllTextAsync(recordPath, cancellationToken)) as JsonObject;
            if (record is null) continue;
            artifacts.Add(PublicArtifact(record));
        }
        await SendDurableResponseAsync(new JsonObject
        {
            ["type"] = "managed_artifacts.result",
            ["request_id"] = requestId,
            ["artifacts"] = artifacts,
        }, requestId, cancellationToken);
    }

    private async Task ManageArtifactAsync(
        JsonElement message,
        CancellationToken cancellationToken)
    {
        var requestId = message.GetProperty("request_id").GetString()!;
        var artifactId = message.GetProperty("artifact_id").GetString()!;
        var action = message.GetProperty("action").GetString()!;
        var root = Path.GetFullPath(Path.Combine(_root, "ManagedArtifacts", SafeName(artifactId)));
        var managedRoot = Path.GetFullPath(Path.Combine(_root, "ManagedArtifacts"))
            + Path.DirectorySeparatorChar;
        var response = new JsonObject
        {
            ["type"] = "managed_artifact.result",
            ["request_id"] = requestId,
            ["status"] = "error",
            ["artifact_id"] = artifactId,
            ["action"] = action,
            ["error_code"] = "LOCAL_FILE_REF.RESOLVE_FAILED",
        };
        if (root.StartsWith(managedRoot, StringComparison.OrdinalIgnoreCase)
            && Directory.Exists(root))
        {
            var recordPath = Path.Combine(root, "artifact.json");
            var record = File.Exists(recordPath)
                ? JsonNode.Parse(await File.ReadAllTextAsync(recordPath, cancellationToken)) as JsonObject
                : null;
            var path = record?["canonical_path"]?.GetValue<string>();
            if (record is not null && path is not null && File.Exists(path)
                && Path.GetFullPath(path).StartsWith(root + Path.DirectorySeparatorChar,
                    StringComparison.OrdinalIgnoreCase))
            {
                if (action == "delete")
                {
                    Directory.Delete(root, true);
                }
                else if (action is "preview" or "open_directory")
                {
                    if (OperatingSystem.IsWindows())
                    {
                        var start = action == "preview"
                            ? new ProcessStartInfo(path) { UseShellExecute = true }
                            : new ProcessStartInfo("explorer.exe", $"/select,\"{path}\"")
                            { UseShellExecute = true };
                        Process.Start(start);
                    }
                    else
                    {
                        await SendDurableResponseAsync(response, requestId, cancellationToken);
                        return;
                    }
                }
                else if (action == "select")
                {
                    response["file"] = await RegisterLocalFileAsync(
                        path,
                        message.GetProperty("scope"),
                        "managed-artifact:" + artifactId,
                        cancellationToken);
                }
                response["status"] = "ok";
                response.Remove("error_code");
            }
        }
        await SendDurableResponseAsync(response, requestId, cancellationToken);
    }

    private static JsonObject PublicArtifact(JsonObject record) => new()
    {
        ["artifact_id"] = record["artifact_id"]!.DeepClone(),
        ["task_id"] = record["task_id"]!.DeepClone(),
        ["display_name"] = record["display_name"]!.DeepClone(),
        ["mime_type"] = record["mime_type"]!.DeepClone(),
        ["size_bytes"] = record["size_bytes"]!.DeepClone(),
        ["created_at"] = record["created_at"]!.DeepClone(),
    };

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

    private static long OutputSize(string taskRoot) =>
        TaskHistory.DiscoverOutputs(taskRoot).Sum(output => output.SizeBytes);

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

    private async Task SendDurableResponseAsync(
        JsonObject message,
        string requestId,
        CancellationToken cancellationToken)
    {
        var outboxPath = Path.Combine(
            _root, "Outbox", $"response-{SafeName(requestId)}.json");
        await File.WriteAllTextAsync(
            outboxPath, message.ToJsonString(JsonOptions.Default), cancellationToken);
        if (await SendAsync(message, cancellationToken)) File.Delete(outboxPath);
    }

    private async Task SendFileErrorAsync(
        string type,
        string requestId,
        string errorCode,
        CancellationToken cancellationToken,
        bool includeFiles = false)
    {
        var response = new JsonObject
        {
            ["type"] = type,
            ["request_id"] = requestId,
            ["status"] = "error",
            ["error_code"] = errorCode,
        };
        if (includeFiles) response["files"] = new JsonArray();
        await SendDurableResponseAsync(response, requestId, cancellationToken);
    }

    private string LocalFileRecordPath(string localFileRef)
    {
        if (!localFileRef.StartsWith("lfr_", StringComparison.Ordinal)
            || SafeName(localFileRef) != localFileRef)
            throw new LocalFileException("LOCAL_FILE_REF.RESOLVE_FAILED");
        return Path.Combine(_root, "LocalFileRefs", localFileRef + ".json");
    }

    private static async Task WriteJsonAtomicallyAsync(
        string path,
        JsonObject value,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
        await File.WriteAllTextAsync(
            temporary, value.ToJsonString(JsonOptions.Default), cancellationToken);
        File.Move(temporary, path, true);
    }

    private static string MimeType(string extension) => extension.ToLowerInvariant() switch
    {
        ".png" => "image/png",
        ".jpg" or ".jpeg" => "image/jpeg",
        ".gif" => "image/gif",
        ".webp" => "image/webp",
        ".pdf" => "application/pdf",
        ".json" => "application/json",
        ".txt" or ".log" => "text/plain",
        ".csv" => "text/csv",
        ".mp3" => "audio/mpeg",
        ".wav" => "audio/wav",
        ".mp4" => "video/mp4",
        ".mov" => "video/quicktime",
        ".zip" => "application/zip",
        _ => "application/octet-stream",
    };

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

    private async Task<List<(JsonObject Descriptor, string Root)>> LoadPublicComponentsAsync(
        string packageRoot,
        CancellationToken cancellationToken)
    {
        var result = new List<(JsonObject Descriptor, string Root)>();
        var declarationPath = Path.Combine(packageRoot, "public-components.json");
        if (!File.Exists(declarationPath)) return result;
        var envelopes = JsonNode.Parse(
            await File.ReadAllTextAsync(declarationPath, cancellationToken)) as JsonArray
            ?? throw new InvalidDataException("public Component declaration is invalid");
        foreach (var item in envelopes)
        {
            var descriptor = item?["descriptor"] as JsonObject
                ?? throw new InvalidDataException("public Component descriptor is missing");
            var componentId = descriptor["component_id"]?.GetValue<string>()
                ?? throw new InvalidDataException("public Component id is missing");
            var componentVersion = descriptor["component_version"]?.GetValue<string>()
                ?? throw new InvalidDataException("public Component version is missing");
            var componentRoot = Path.Combine(
                _root,
                "Components",
                SafeName(componentId),
                SafeName(componentVersion));
            var installedDescriptorPath = Path.Combine(componentRoot, "descriptor.json");
            if (!File.Exists(installedDescriptorPath))
                throw new FileNotFoundException(
                    "public Component is not installed",
                    componentId);
            var installed = JsonNode.Parse(
                await File.ReadAllTextAsync(installedDescriptorPath, cancellationToken));
            if (!JsonNode.DeepEquals(installed, descriptor))
                throw new InvalidDataException("installed public Component descriptor mismatch");
            result.Add((descriptor, componentRoot));
        }
        return result;
    }

    private static string ResolveEntrypoint(
        string packageRoot,
        JsonElement entrypoint,
        List<(JsonObject Descriptor, string Root)> components)
    {
        if (entrypoint.TryGetProperty("executable", out var privateExecutable))
            return PathInside(packageRoot, privateExecutable.GetString()!);
        var componentId = entrypoint.GetProperty("component_id").GetString()!;
        var exportName = entrypoint.GetProperty("export").GetString()!;
        var component = components.FirstOrDefault(item =>
            item.Descriptor["component_id"]?.GetValue<string>() == componentId);
        if (component.Descriptor is null)
            throw new InvalidDataException("entrypoint public Component is not installed");
        var exports = component.Descriptor["exports"] as JsonObject
            ?? throw new InvalidDataException("public Component exports are invalid");
        var relativePath = exports[exportName]?.GetValue<string>()
            ?? throw new InvalidDataException("public Component export is missing");
        return PathInside(component.Root, relativePath);
    }

    private static void ApplyComponentEnvironment(
        ProcessStartInfo start,
        JsonElement capabilityDescriptor,
        List<(JsonObject Descriptor, string Root)> components)
    {
        var pathEntries = new List<string>();
        var pythonPaths = new List<string>();
        foreach (var component in components)
        {
            if (component.Descriptor["path_entries"] is JsonArray paths)
            {
                pathEntries.AddRange(paths.Select(item =>
                    PathInside(component.Root, item!.GetValue<string>())));
            }
            if (component.Descriptor["environment_paths"] is not JsonObject environment)
                continue;
            if (environment["PYTHONHOME"] is JsonArray homes && homes.Count > 0)
                start.Environment["PYTHONHOME"] = PathInside(
                    component.Root,
                    homes[0]!.GetValue<string>());
            if (environment["PYTHONPATH"] is JsonArray declaredPythonPaths)
            {
                pythonPaths.AddRange(declaredPythonPaths.Select(item =>
                    PathInside(component.Root, item!.GetValue<string>())));
            }
        }
        if (pathEntries.Count > 0)
        {
            var existing = start.Environment.TryGetValue("PATH", out var value)
                ? value
                : Environment.GetEnvironmentVariable("PATH");
            start.Environment["PATH"] = string.Join(
                Path.PathSeparator,
                pathEntries.Append(existing ?? string.Empty));
        }
        if (pythonPaths.Count > 0)
            start.Environment["PYTHONPATH"] = string.Join(
                Path.PathSeparator,
                pythonPaths);
        if (!capabilityDescriptor.TryGetProperty(
                "component_exports",
                out var exportBindings)) return;
        var boundVariables = new HashSet<string>(StringComparer.Ordinal);
        foreach (var binding in exportBindings.EnumerateArray())
        {
            var variable = binding.GetProperty(
                "environment_variable").GetString()!;
            if (!boundVariables.Add(variable))
                throw new InvalidDataException(
                    "public Component export environment variable is duplicated");
            if (start.Environment.ContainsKey(variable))
                throw new InvalidDataException(
                    "public Component export environment variable is already set");
            var componentId = binding.GetProperty(
                "component_id").GetString()!;
            var exportName = binding.GetProperty("export").GetString()!;
            var component = components.FirstOrDefault(item =>
                item.Descriptor["component_id"]?.GetValue<string>() == componentId);
            if (component.Descriptor is null)
                throw new InvalidDataException(
                    "public Component export binding references an undeclared component");
            var exports = component.Descriptor["exports"] as JsonObject
                ?? throw new InvalidDataException(
                    "public Component exports are invalid");
            var relativePath = exports[exportName]?.GetValue<string>()
                ?? throw new InvalidDataException(
                    "public Component export binding is missing");
            start.Environment[variable] = PathInside(
                component.Root,
                relativePath);
        }
    }

    private static string ExpandArgument(
        string value,
        string packageRoot,
        string taskRoot) => value
        .Replace("{package_root}", packageRoot, StringComparison.Ordinal)
        .Replace("{task_root}", taskRoot, StringComparison.Ordinal);

    private static string PathInside(string root, string relativePath)
    {
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var path = Path.GetFullPath(Path.Combine(root, relativePath));
        if (!path.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("declared path escapes install root");
        return path;
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

internal sealed class LocalFileException : Exception
{
    public string Code { get; }

    public LocalFileException(string code) : base(code) => Code = code;
}

internal static class NativeFileDialog
{
    private const int OfnExplorer = 0x00080000;
    private const int OfnAllowMultiSelect = 0x00000200;
    private const int OfnFileMustExist = 0x00001000;
    private const int OfnPathMustExist = 0x00000800;
    private const int OfnNoChangeDir = 0x00000008;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct OpenFileName
    {
        public int StructSize;
        public IntPtr Owner;
        public IntPtr Instance;
        [MarshalAs(UnmanagedType.LPWStr)] public string? Filter;
        [MarshalAs(UnmanagedType.LPWStr)] public string? CustomFilter;
        public int MaxCustomFilter;
        public int FilterIndex;
        public IntPtr File;
        public int MaxFile;
        public IntPtr FileTitle;
        public int MaxFileTitle;
        [MarshalAs(UnmanagedType.LPWStr)] public string? InitialDirectory;
        [MarshalAs(UnmanagedType.LPWStr)] public string? Title;
        public int Flags;
        public short FileOffset;
        public short FileExtension;
        [MarshalAs(UnmanagedType.LPWStr)] public string? DefaultExtension;
        public IntPtr CustomData;
        public IntPtr Hook;
        [MarshalAs(UnmanagedType.LPWStr)] public string? TemplateName;
        public IntPtr Reserved;
        public int Reserved2;
        public int FlagsExtended;
    }

    [DllImport("comdlg32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetOpenFileName(ref OpenFileName openFileName);

    public static List<string>? SelectFiles(JsonElement selector)
    {
        const int characters = 65536;
        var buffer = Marshal.AllocHGlobal(characters * sizeof(char));
        try
        {
            for (var offset = 0; offset < characters * sizeof(char); offset += sizeof(long))
                Marshal.WriteInt64(buffer, offset, 0);
            var filter = BuildFilter(selector);
            var multiple = selector.TryGetProperty("multiple", out var multipleValue)
                && multipleValue.GetBoolean();
            var dialog = new OpenFileName
            {
                StructSize = Marshal.SizeOf<OpenFileName>(),
                Filter = filter,
                File = buffer,
                MaxFile = characters,
                Title = "选择文件",
                Flags = OfnExplorer | OfnFileMustExist | OfnPathMustExist | OfnNoChangeDir
                    | (multiple ? OfnAllowMultiSelect : 0),
            };
            if (!GetOpenFileName(ref dialog)) return null;
            var raw = Marshal.PtrToStringUni(buffer, characters) ?? string.Empty;
            var parts = raw.Split('\0', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0) return null;
            if (parts.Length == 1) return new List<string> { parts[0] };
            return parts.Skip(1).Select(name => Path.Combine(parts[0], name)).ToList();
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    private static string BuildFilter(JsonElement selector)
    {
        if (selector.TryGetProperty("accept_extensions", out var extensions)
            && extensions.GetArrayLength() > 0)
        {
            var patterns = string.Join(';', extensions.EnumerateArray()
                .Select(item => "*" + item.GetString()));
            return $"Allowed files\0{patterns}\0All files\0*.*\0\0";
        }
        return "All files\0*.*\0\0";
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
