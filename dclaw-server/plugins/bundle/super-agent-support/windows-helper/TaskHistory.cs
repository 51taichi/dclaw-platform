using System.Text.Json;
using System.Text.Json.Nodes;

namespace DClaw.LocalHelper;

internal sealed record LocalTaskOutput(
    string Name,
    string FullPath,
    long SizeBytes);

internal sealed record LocalTaskItem(
    string TaskId,
    string AgentName,
    string CapabilityId,
    string Status,
    DateTimeOffset UpdatedAt,
    string TaskRoot,
    IReadOnlyList<LocalTaskOutput> Outputs,
    string? ErrorCode);

internal static class TaskHistory
{
    internal const string StateFileName = "task-state.json";

    private static readonly HashSet<string> InternalFiles = new(
        StringComparer.OrdinalIgnoreCase)
    {
        "input.json",
        "continuation.json",
        "result.json",
        "checkpoint.json",
        "capability.id",
        "agent.name",
        ".credentials.json",
        ".sequence",
        StateFileName,
        "stdout.log",
        "stderr.log",
    };

    internal static async Task TryWriteAsync(
        string taskRoot,
        string taskId,
        string agentName,
        string capabilityId,
        string status,
        string? errorCode,
        CancellationToken cancellationToken)
    {
        try
        {
            var statePath = Path.Combine(taskRoot, StateFileName);
            var existing = File.Exists(statePath)
                ? JsonNode.Parse(await File.ReadAllTextAsync(
                    statePath,
                    cancellationToken)) as JsonObject
                : null;
            var now = DateTimeOffset.UtcNow;
            var outputs = new JsonArray(
                DiscoverOutputs(taskRoot)
                    .Select(output => (JsonNode)new JsonObject
                    {
                        ["name"] = output.Name,
                        ["relative_path"] = Path.GetRelativePath(
                                taskRoot,
                                output.FullPath)
                            .Replace(Path.DirectorySeparatorChar, '/'),
                        ["size_bytes"] = output.SizeBytes,
                    })
                    .ToArray());
            var state = new JsonObject
            {
                ["task_id"] = taskId,
                ["agent_name"] = agentName,
                ["capability_id"] = capabilityId,
                ["status"] = status,
                ["created_at"] = existing?["created_at"]?.DeepClone()
                    ?? now.ToUnixTimeSeconds(),
                ["updated_at"] = now.ToUnixTimeSeconds(),
                ["outputs"] = outputs,
            };
            if (!string.IsNullOrWhiteSpace(errorCode))
                state["error_code"] = errorCode;
            await WriteAtomicallyAsync(statePath, state, cancellationToken);
        }
        catch
        {
            // Task bookkeeping must never make capability execution fail.
        }
    }

    internal static IReadOnlyList<LocalTaskItem> Load(string root)
    {
        var tasksRoot = Path.Combine(root, "Tasks");
        if (!Directory.Exists(tasksRoot)) return Array.Empty<LocalTaskItem>();
        var items = new List<LocalTaskItem>();
        foreach (var taskRoot in Directory.EnumerateDirectories(
                     tasksRoot,
                     "*",
                     SearchOption.AllDirectories))
        {
            var statePath = Path.Combine(taskRoot, StateFileName);
            var capabilityPath = Path.Combine(taskRoot, "capability.id");
            if (!File.Exists(statePath) && !File.Exists(capabilityPath)) continue;
            try
            {
                var state = File.Exists(statePath)
                    ? JsonNode.Parse(File.ReadAllText(statePath)) as JsonObject
                    : null;
                var taskId = state?["task_id"]?.GetValue<string>()
                    ?? Path.GetFileName(taskRoot);
                var agentName = state?["agent_name"]?.GetValue<string>()
                    ?? ReadText(Path.Combine(taskRoot, "agent.name"))
                    ?? Path.GetFileName(Path.GetDirectoryName(taskRoot))
                    ?? "本地任务";
                var capabilityId = state?["capability_id"]?.GetValue<string>()
                    ?? ReadText(capabilityPath)
                    ?? string.Empty;
                var status = state?["status"]?.GetValue<string>()
                    ?? (File.Exists(Path.Combine(taskRoot, "result.json"))
                        ? "completed"
                        : File.Exists(Path.Combine(taskRoot, "checkpoint.json"))
                            ? "waiting"
                            : "unknown");
                var updatedSeconds = state?["updated_at"]?.GetValue<long>();
                var updatedAt = updatedSeconds is > 0
                    ? DateTimeOffset.FromUnixTimeSeconds(updatedSeconds.Value)
                    : new DateTimeOffset(Directory.GetLastWriteTimeUtc(taskRoot));
                items.Add(new LocalTaskItem(
                    taskId,
                    agentName,
                    capabilityId,
                    status,
                    updatedAt,
                    taskRoot,
                    DiscoverOutputs(taskRoot),
                    state?["error_code"]?.GetValue<string>()));
            }
            catch (IOException)
            {
                // A running task may be replacing its state file during refresh.
            }
            catch (JsonException)
            {
                // Ignore incomplete legacy task metadata.
            }
        }
        return items
            .OrderByDescending(item => item.UpdatedAt)
            .Take(200)
            .ToArray();
    }

    internal static IReadOnlyList<LocalTaskOutput> DiscoverOutputs(string taskRoot)
    {
        if (!Directory.Exists(taskRoot)) return Array.Empty<LocalTaskOutput>();
        var fullTaskRoot = Path.GetFullPath(taskRoot)
            .TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var bindingsRoot = Path.GetFullPath(
                Path.Combine(taskRoot, "res", "bindings"))
            .TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var outputs = new List<LocalTaskOutput>();
        foreach (var path in Directory.EnumerateFiles(
                     taskRoot,
                     "*",
                     SearchOption.AllDirectories))
        {
            var fullPath = Path.GetFullPath(path);
            if (!fullPath.StartsWith(fullTaskRoot, StringComparison.OrdinalIgnoreCase)
                || fullPath.StartsWith(bindingsRoot, StringComparison.OrdinalIgnoreCase)
                || InternalFiles.Contains(Path.GetFileName(fullPath))
                || Path.GetFileName(fullPath).StartsWith('.'))
                continue;
            var info = new FileInfo(fullPath);
            outputs.Add(new LocalTaskOutput(info.Name, fullPath, info.Length));
        }
        return outputs
            .OrderByDescending(output => new FileInfo(output.FullPath).LastWriteTimeUtc)
            .Take(200)
            .ToArray();
    }

    internal static void OpenFile(string path)
    {
        if (!File.Exists(path)) return;
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path)
        {
            UseShellExecute = true,
        });
    }

    internal static void OpenDirectory(string path, bool selectFile = false)
    {
        var target = selectFile && File.Exists(path)
            ? path
            : Directory.Exists(path)
                ? path
                : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(target)) return;
        var arguments = selectFile && File.Exists(target)
            ? $"/select,\"{target}\""
            : $"\"{target}\"";
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(
            "explorer.exe",
            arguments)
        {
            UseShellExecute = true,
        });
    }

    private static string? ReadText(string path) => File.Exists(path)
        ? File.ReadAllText(path).Trim()
        : null;

    private static async Task WriteAtomicallyAsync(
        string path,
        JsonObject value,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
        await File.WriteAllTextAsync(
            temporary,
            value.ToJsonString(JsonOptions.Default),
            cancellationToken);
        File.Move(temporary, path, true);
    }
}
