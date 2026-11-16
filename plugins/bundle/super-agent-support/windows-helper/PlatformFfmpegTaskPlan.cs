using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace DClaw.LocalHelper;

internal static class PlatformFfmpegTaskPlan
{
    internal const string CapabilityId = "dclaw.ffmpeg.task.plan";
    internal const string PackageVersion = "0.1.0";
    internal const string ComponentVersion = "N-128100-gceb466cbcd";

    private static readonly Regex OutputName = new(
        @"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.mp4$", RegexOptions.CultureInvariant);
    private static readonly Regex SlotName = new(
        @"^[a-z][a-z0-9_]{0,63}$", RegexOptions.CultureInvariant);
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
            as JsonObject ?? throw new InvalidDataException("video render input is invalid");
        var planVersion = input["plan_version"]?.GetValue<string>();
        if (planVersion is not ("1" or "2")
            || input["clips"] is not JsonArray clips || clips.Count is < 1 or > 16
            || input["output"] is not JsonObject output)
            throw new InvalidDataException("video render plan is invalid");
        var outputName = output["filename"]?.GetValue<string>()
            ?? throw new InvalidDataException("output filename is missing");
        var width = output["width"]?.GetValue<int>() ?? 0;
        var height = output["height"]?.GetValue<int>() ?? 0;
        var fps = output["fps"]?.GetValue<int>() ?? 0;
        var audio = output["audio_policy"]?.GetValue<string>();
        if (!OutputName.IsMatch(outputName) || Reserved.Contains(outputName)
            || width is < 16 or > 3840 || height is < 16 or > 2160
            || width % 2 != 0 || height % 2 != 0 || fps is < 1 or > 60
            || audio is not ("mute" or "preserve"))
            throw new InvalidDataException("video output plan is invalid");

        var usedSlots = new HashSet<string>(StringComparer.Ordinal);
        var filter = new List<string>();
        var start = new ProcessStartInfo(ffmpeg)
        {
            WorkingDirectory = taskRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var fixedArgument in new[] { "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y" })
            start.ArgumentList.Add(fixedArgument);
        for (var index = 0; index < clips.Count; index++)
        {
            var clip = clips[index] as JsonObject
                ?? throw new InvalidDataException("clip plan is invalid");
            var slot = clip["slot"]?.GetValue<string>()
                ?? throw new InvalidDataException("clip slot is missing");
            if (!SlotName.IsMatch(slot))
                throw new InvalidDataException("clip slot is invalid");
            var hasStart = clip.ContainsKey("trim_start_ms");
            var hasEnd = clip.ContainsKey("trim_end_ms");
            if (hasStart != hasEnd || (planVersion == "1" && !hasStart))
                throw new InvalidDataException("clip trim range is incomplete");
            var from = hasStart ? clip["trim_start_ms"]!.GetValue<int>() : 0;
            var to = hasEnd ? clip["trim_end_ms"]!.GetValue<int>() : 0;
            if (hasStart && (from < 0 || to <= from || to > 86400000))
                throw new InvalidDataException("clip trim range is invalid");
            var relative = input[slot]?.GetValue<string>()
                ?? throw new InvalidDataException("clip slot is not bound");
            var bindingRoot = Path.GetFullPath(Path.Combine(taskRoot, "res", "bindings", slot));
            var path = Path.GetFullPath(Path.Combine(taskRoot, relative));
            if (!path.StartsWith(bindingRoot + Path.DirectorySeparatorChar,
                    StringComparison.OrdinalIgnoreCase) || !File.Exists(path))
                throw new InvalidDataException("clip is outside its binding");
            usedSlots.Add(slot);
            start.ArgumentList.Add("-i");
            start.ArgumentList.Add(path);
            var video = hasStart
                ? $"[{index}:v]trim=start={Seconds(from)}:end={Seconds(to)},setpts=PTS-STARTPTS"
                : $"[{index}:v]setpts=PTS-STARTPTS";
            if (clip["crop"] is JsonObject crop)
            {
                var x = crop["x"]?.GetValue<int>() ?? -1;
                var y = crop["y"]?.GetValue<int>() ?? -1;
                var w = crop["width"]?.GetValue<int>() ?? 0;
                var h = crop["height"]?.GetValue<int>() ?? 0;
                if (x < 0 || y < 0 || w < 2 || h < 2)
                    throw new InvalidDataException("clip crop is invalid");
                video += $",crop={w}:{h}:{x}:{y}";
            }
            video += $",scale={width}:{height}:force_original_aspect_ratio=decrease";
            video += $",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1,format=yuv420p[v{index}]";
            filter.Add(video);
            if (audio == "preserve")
                filter.Add(hasStart
                    ? $"[{index}:a]atrim=start={Seconds(from)}:end={Seconds(to)},asetpts=PTS-STARTPTS,aresample=48000[a{index}]"
                    : $"[{index}:a]asetpts=PTS-STARTPTS,aresample=48000[a{index}]");
        }
        var boundSlots = input.Select(item => item.Key)
            .Where(key => key != "plan_version" && key != "clips" && key != "output")
            .ToHashSet(StringComparer.Ordinal);
        if (!usedSlots.SetEquals(boundSlots))
            throw new InvalidDataException("video bindings do not match timeline");
        var inputs = string.Concat(Enumerable.Range(0, clips.Count)
            .Select(index => audio == "preserve" ? $"[v{index}][a{index}]" : $"[v{index}]"));
        filter.Add($"{inputs}concat=n={clips.Count}:v=1:a={(audio == "preserve" ? 1 : 0)}[video]" +
            (audio == "preserve" ? "[sound]" : ""));
        start.ArgumentList.Add("-filter_complex");
        start.ArgumentList.Add(string.Join(';', filter));
        start.ArgumentList.Add("-map");
        start.ArgumentList.Add("[video]");
        if (audio == "preserve")
        {
            start.ArgumentList.Add("-map");
            start.ArgumentList.Add("[sound]");
            start.ArgumentList.Add("-c:a");
            start.ArgumentList.Add("aac");
        }
        start.ArgumentList.Add("-c:v");
        start.ArgumentList.Add("libx264");
        start.ArgumentList.Add("-pix_fmt");
        start.ArgumentList.Add("yuv420p");
        start.ArgumentList.Add(Path.Combine(taskRoot, outputName));

        using var process = Process.Start(start)
            ?? throw new InvalidOperationException("FFmpeg did not start");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(stdout, stderr);
        if (process.ExitCode != 0) return 1;
        var rendered = Path.Combine(taskRoot, outputName);
        var info = new FileInfo(rendered);
        if (!info.Exists || info.Length == 0)
            throw new InvalidDataException("rendered video is missing or empty");
        using var stream = File.OpenRead(rendered);
        var result = new JsonArray(new JsonObject
        {
            ["name"] = outputName,
            ["size_bytes"] = info.Length,
            ["sha256"] = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(),
        });
        File.WriteAllText(Path.Combine(taskRoot, "result.json"),
            new JsonObject { ["outputs"] = result }.ToJsonString());
        return 0;
    }

    private static string Seconds(int milliseconds) =>
        (milliseconds / 1000m).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);

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
