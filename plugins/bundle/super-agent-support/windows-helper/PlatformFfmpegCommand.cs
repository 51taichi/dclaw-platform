using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace DClaw.LocalHelper;

internal static class PlatformFfmpegCommand
{
    internal const string CapabilityId = "dclaw.ffmpeg.command";
    internal const string PackageVersion = "0.1.0";
    internal const string ComponentVersion = "N-128100-gceb466cbcd";

    private static readonly Regex InputToken = new(
        @"^\{input:([a-z][a-z0-9_]{0,63})\}$", RegexOptions.CultureInvariant);
    private static readonly Regex OutputToken = new(
        @"^\{output:([A-Za-z0-9][A-Za-z0-9._-]{0,127})\}$", RegexOptions.CultureInvariant);
    private static readonly Regex OutputName = new(
        @"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", RegexOptions.CultureInvariant);
    private static readonly HashSet<string> Reserved = new(StringComparer.OrdinalIgnoreCase)
    {
        "input.json", "continuation.json", "result.json", "checkpoint.json",
        "task-state.json", "capability.id", "agent.name", "stdout.log", "stderr.log",
    };

    internal static bool IsComponentReady(string helperRoot)
    {
        try { return File.Exists(ResolveFfmpeg(helperRoot)); }
        catch (Exception) { return false; }
    }

    internal static int Execute(string helperRoot, string taskRoot)
    {
        var ffmpeg = ResolveFfmpeg(helperRoot);
        if (!File.Exists(ffmpeg))
            throw new FileNotFoundException("registered FFmpeg Component is unavailable");
        var input = JsonNode.Parse(File.ReadAllText(Path.Combine(taskRoot, "input.json")))
            as JsonObject ?? throw new InvalidDataException("FFmpeg task input is invalid");
        var arguments = input["arguments"] as JsonArray
            ?? throw new InvalidDataException("FFmpeg arguments are missing");
        var outputs = input["output_files"] as JsonArray
            ?? throw new InvalidDataException("FFmpeg outputs are missing");
        if (arguments.Count is < 1 or > 128 || outputs.Count is < 1 or > 8)
            throw new InvalidDataException("FFmpeg argument or output count is invalid");
        var outputNames = outputs.Select(item => item?.GetValue<string>()
            ?? throw new InvalidDataException("FFmpeg output name is invalid")).ToList();
        if (outputNames.Any(name => !OutputName.IsMatch(name) || Reserved.Contains(name))
            || outputNames.Distinct(StringComparer.OrdinalIgnoreCase).Count() != outputNames.Count)
            throw new InvalidDataException("FFmpeg output declaration is invalid");

        var usedInputs = new HashSet<string>(StringComparer.Ordinal);
        var usedOutputs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var start = new ProcessStartInfo(ffmpeg)
        {
            WorkingDirectory = taskRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var fixedArgument in new[] { "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y" })
            start.ArgumentList.Add(fixedArgument);
        string? previous = null;
        foreach (var node in arguments)
        {
            var value = node?.GetValue<string>()
                ?? throw new InvalidDataException("FFmpeg argument is invalid");
            if (value.Length is < 1 or > 2048)
                throw new InvalidDataException("FFmpeg argument length is invalid");
            var inputMatch = InputToken.Match(value);
            var outputMatch = OutputToken.Match(value);
            if (inputMatch.Success)
            {
                if (previous != "-i")
                    throw new InvalidDataException("bound input must follow -i");
                var slot = inputMatch.Groups[1].Value;
                var relative = input[slot]?.GetValue<string>()
                    ?? throw new InvalidDataException("input slot is not bound");
                var bindingRoot = Path.GetFullPath(Path.Combine(taskRoot, "res", "bindings", slot));
                var path = Path.GetFullPath(Path.Combine(taskRoot, relative));
                if (!path.StartsWith(bindingRoot + Path.DirectorySeparatorChar,
                        StringComparison.OrdinalIgnoreCase) || !File.Exists(path))
                    throw new InvalidDataException("input slot is outside its binding");
                usedInputs.Add(slot);
                start.ArgumentList.Add(path);
            }
            else if (outputMatch.Success)
            {
                var name = outputMatch.Groups[1].Value;
                if (!outputNames.Contains(name, StringComparer.OrdinalIgnoreCase)
                    || !usedOutputs.Add(name))
                    throw new InvalidDataException("output is not declared once");
                start.ArgumentList.Add(Path.Combine(taskRoot, name));
            }
            else
            {
                if (previous == "-i" || value.Contains("..", StringComparison.Ordinal)
                    || value.Contains("://", StringComparison.Ordinal)
                    || value.Contains('\\') || value.Contains('/')
                    || value.Contains('\0') || value.Contains('\r') || value.Contains('\n')
                    || value.StartsWith("file:", StringComparison.OrdinalIgnoreCase)
                    || value.StartsWith("pipe:", StringComparison.OrdinalIgnoreCase)
                    || value.StartsWith('~')
                    || Regex.IsMatch(value, @"^[A-Za-z]:")
                    || Regex.IsMatch(value, @"(?:movie|amovie|subtitles|drawtext|sendcmd|asendcmd|zmq|azmq)\s*=", RegexOptions.IgnoreCase))
                    throw new InvalidDataException("raw path, URL, or external filter is not allowed");
                start.ArgumentList.Add(value);
            }
            previous = value;
        }
        var boundSlots = input.Select(item => item.Key)
            .Where(key => key != "arguments" && key != "output_files")
            .ToHashSet(StringComparer.Ordinal);
        if (!usedInputs.SetEquals(boundSlots)
            || !usedOutputs.SetEquals(outputNames))
            throw new InvalidDataException("FFmpeg bindings or outputs do not match arguments");

        using var process = Process.Start(start)
            ?? throw new InvalidOperationException("FFmpeg did not start");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(stdout, stderr);
        if (process.ExitCode != 0) return 1;
        var result = new JsonArray();
        foreach (var name in outputNames)
        {
            var path = Path.Combine(taskRoot, name);
            var info = new FileInfo(path);
            if (!info.Exists || info.Length == 0)
                throw new InvalidDataException("declared FFmpeg output is missing or empty");
            using var stream = File.OpenRead(path);
            result.Add(new JsonObject
            {
                ["name"] = name,
                ["size_bytes"] = info.Length,
                ["sha256"] = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(),
            });
        }
        File.WriteAllText(Path.Combine(taskRoot, "result.json"),
            new JsonObject { ["outputs"] = result }.ToJsonString());
        return 0;
    }

    private static string ComponentRoot(string helperRoot) => Path.Combine(
        helperRoot, "Components", "ffmpeg", ComponentVersion);

    private static string ResolveFfmpeg(string helperRoot)
    {
        var root = ComponentRoot(helperRoot);
        var descriptorPath = Path.Combine(root, "descriptor.json");
        if (!File.Exists(descriptorPath)) return string.Empty;
        using var document = JsonDocument.Parse(File.ReadAllText(descriptorPath));
        var descriptor = document.RootElement;
        if (descriptor.GetProperty("component_id").GetString() != "ffmpeg"
            || descriptor.GetProperty("component_version").GetString() != ComponentVersion)
            throw new InvalidDataException("FFmpeg Component version mismatch");
        var relative = descriptor.GetProperty("exports").GetProperty("ffmpeg").GetString()!;
        var path = Path.GetFullPath(Path.Combine(root, relative));
        if (!path.StartsWith(Path.GetFullPath(root) + Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("FFmpeg Component export escapes install root");
        return path;
    }
}
