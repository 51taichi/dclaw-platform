using System.Net;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace DClaw.LocalHelper;

internal static class HelperRegression
{
    private sealed class AssetsHandler : HttpMessageHandler
    {
        internal bool Fail { get; set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (Fail) return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
            var content = request.RequestUri!.AbsolutePath.EndsWith("/two")
                ? Encoding.UTF8.GetBytes("second")
                : Encoding.UTF8.GetBytes("first");
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(content),
            });
        }
    }

    private static string Asset(string id, string slot, string text, int order)
    {
        var content = Encoding.UTF8.GetBytes(text);
        return JsonSerializer.Serialize(new
        {
            asset_id = id, slot, usage = "timeline_clip", order,
            destination = "res", name = slot + ".mp4",
            size_bytes = content.Length,
            sha256 = Convert.ToHexString(SHA256.HashData(content)).ToLowerInvariant(),
            download_url = "https://assets.example/" + (order == 1 ? "two" : "one"),
        });
    }

    private static async Task<JsonElement> Run(
        HelperRuntime runtime, string root, string taskId, string assets)
    {
        var input = JsonSerializer.Serialize(new
        {
            type = "aigc.assets.localize",
            task = new
            {
                task_id = taskId, task_root_name = "test",
                material_task_id = "material",
                assets = JsonSerializer.Deserialize<JsonElement>("[" + assets + "]"),
            },
        });
        using (var document = JsonDocument.Parse(input))
        {
            var handle = typeof(HelperRuntime).GetMethod(
                "HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            await (Task)handle.Invoke(runtime, new object[] {
                document.RootElement, CancellationToken.None,
            })!;
        }
        var path = Path.Combine(root, "Outbox");
        for (var attempt = 0; attempt < 200; attempt++)
        {
            var terminal = Directory.GetFiles(path, taskId + "-*.json")
                .Select(File.ReadAllText)
                .Select(value => JsonDocument.Parse(value))
                .FirstOrDefault(item => item.RootElement.GetProperty("event_type").GetString()
                    is "completed" or "failed");
            if (terminal is not null) return terminal.RootElement.Clone();
            await Task.Delay(25);
        }
        throw new Exception("Helper did not finish task");
    }

    private static async Task<JsonElement> RunTaskMessage(
        HelperRuntime runtime, string root, string taskId, string input)
    {
        var handle = typeof(HelperRuntime).GetMethod(
            "HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
        using (var document = JsonDocument.Parse(input))
            await (Task)handle.Invoke(runtime, new object[] {
                document.RootElement, CancellationToken.None,
            })!;
        for (var attempt = 0; attempt < 200; attempt++)
        {
            foreach (var path in Directory.GetFiles(Path.Combine(root, "Outbox"), taskId + "-*.json"))
            {
                using var eventDocument = JsonDocument.Parse(File.ReadAllText(path));
                if (eventDocument.RootElement.GetProperty("event_type").GetString()
                    is "completed" or "failed")
                    return eventDocument.RootElement.Clone();
            }
            await Task.Delay(25);
        }
        throw new Exception("task did not emit a terminal event after input document disposal");
    }

    private static void Check(bool condition, string reason)
    {
        if (!condition) throw new Exception(reason);
    }

    private static void CheckPlatformFfmpegTaskPlan(string root)
    {
        if (OperatingSystem.IsWindows()) return;
        var componentRoot = Path.Combine(root, "Components", "ffmpeg",
            PlatformFfmpegTaskPlan.ComponentVersion);
        var executable = Path.Combine(componentRoot, "bin", "ffmpeg");
        Directory.CreateDirectory(Path.GetDirectoryName(executable)!);
        File.WriteAllText(executable,
            "#!/bin/sh\nfor last; do :; done\nprintf finished > \"$last\"\n");
        File.SetUnixFileMode(executable, UnixFileMode.UserRead | UnixFileMode.UserExecute);
        File.WriteAllText(Path.Combine(componentRoot, "descriptor.json"),
            JsonSerializer.Serialize(new
            {
                component_id = "ffmpeg",
                component_version = PlatformFfmpegTaskPlan.ComponentVersion,
                exports = new { ffmpeg = "bin/ffmpeg" },
            }));
        Check(PlatformFfmpegTaskPlan.IsComponentReady(root),
            "built-in FFmpeg capability did not find its Component");
        var task = Path.Combine(root, "Tasks", "ffmpeg-test");
        var input = Path.Combine(task, "res", "bindings", "clip_01", "source.mp4");
        Directory.CreateDirectory(Path.GetDirectoryName(input)!);
        File.WriteAllText(input, "source");
        var request = new JsonObject
        {
            ["plan_version"] = "1",
            ["clips"] = new JsonArray(new JsonObject
            {
                ["slot"] = "clip_01", ["trim_start_ms"] = 0, ["trim_end_ms"] = 800,
            }),
            ["output"] = new JsonObject
            {
                ["filename"] = "final.mp4", ["width"] = 64, ["height"] = 64,
                ["fps"] = 5, ["audio_policy"] = "mute",
            },
            ["clip_01"] = "res/bindings/clip_01/source.mp4",
        };
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        Check(PlatformFfmpegTaskPlan.Execute(root, task) == 0,
            "built-in video render failed");
        var result = JsonNode.Parse(File.ReadAllText(Path.Combine(task, "result.json")))!;
        var output = result["outputs"]![0]!;
        Check(output["size_bytes"]!.GetValue<long>() == 8,
            "built-in FFmpeg output size is wrong");
        Check(output["sha256"]!.GetValue<string>() == Convert.ToHexString(
                SHA256.HashData(File.ReadAllBytes(Path.Combine(task, "final.mp4"))))
            .ToLowerInvariant(), "built-in FFmpeg output hash is wrong");
        request["arguments"] = new JsonArray("-i", "https://invalid.test/source.mp4");
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        try
        {
            PlatformFfmpegTaskPlan.Execute(root, task);
            throw new Exception("raw FFmpeg arguments were accepted");
        }
        catch (InvalidDataException) { }
        request.Remove("arguments");
        request["output"]!["filename"] = "result.json";
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        try
        {
            PlatformFfmpegTaskPlan.Execute(root, task);
            throw new Exception("task control file was accepted as output");
        }
        catch (InvalidDataException) { }
        request["output"]!["filename"] = "final.mp4";
        request["clips"]![0]!["trim_end_ms"] = 0;
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        try
        {
            PlatformFfmpegTaskPlan.Execute(root, task);
            throw new Exception("invalid trim range was accepted");
        }
        catch (InvalidDataException) { }
        request["clips"]![0]!["trim_end_ms"] = 800;
        request["clip_01"] = "../private.mp4";
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        try
        {
            PlatformFfmpegTaskPlan.Execute(root, task);
            throw new Exception("untrusted binding path was accepted");
        }
        catch (InvalidDataException) { }
        request["clip_01"] = "res/bindings/clip_01/source.mp4";

        var actualFfmpeg = (Environment.GetEnvironmentVariable("PATH") ?? "")
            .Split(Path.PathSeparator)
            .Select(directory => Path.Combine(directory, "ffmpeg"))
            .FirstOrDefault(File.Exists);
        if (actualFfmpeg is null) return;
        File.Delete(executable);
        File.Copy(actualFfmpeg, executable);
        for (var index = 1; index <= 2; index++)
        {
            var clip = Path.Combine(task, "res", "bindings",
                $"clip_{index:00}", "source.mp4");
            Directory.CreateDirectory(Path.GetDirectoryName(clip)!);
            var generate = Process.Start(new ProcessStartInfo(executable)
            {
                UseShellExecute = false,
                ArgumentList = {
                    "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", index == 1
                        ? "color=c=red:s=64x64:r=5"
                        : "color=c=blue:s=64x64:r=5",
                    "-t", "1", "-c:v", "mpeg4", clip,
                },
            })!;
            generate.WaitForExit();
            Check(generate.ExitCode == 0, "FFmpeg test input generation failed");
        }
        (request["clips"] as JsonArray)!.Add(new JsonObject
        {
            ["slot"] = "clip_02", ["trim_start_ms"] = 100, ["trim_end_ms"] = 900,
        });
        request["clip_02"] = "res/bindings/clip_02/source.mp4";
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        Check(PlatformFfmpegTaskPlan.Execute(root, task) == 0
            && new FileInfo(Path.Combine(task, "final.mp4")).Length > 0,
            "two bound MP4 files did not produce a video");

        for (var index = 1; index <= 2; index++)
        {
            var clip = Path.Combine(task, "res", "bindings",
                $"clip_{index:00}", "source.mp4");
            var withAudio = Process.Start(new ProcessStartInfo(executable)
            {
                UseShellExecute = false,
                ArgumentList = {
                    "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=red:s=64x64:r=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "1", "-c:v", "mpeg4", "-c:a", "aac", clip,
                },
            })!;
            withAudio.WaitForExit();
            Check(withAudio.ExitCode == 0, "FFmpeg audio input generation failed");
        }
        request["output"]!["audio_policy"] = "preserve";
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        Check(PlatformFfmpegTaskPlan.Execute(root, task) == 0,
            "two audio MP4 files did not produce a video");
        var audioProbe = Process.Start(new ProcessStartInfo(executable)
        {
            UseShellExecute = false,
            ArgumentList = {
                "-hide_banner", "-loglevel", "error", "-i",
                Path.Combine(task, "final.mp4"), "-map", "0:a:0", "-f", "null", "-",
            },
        })!;
        audioProbe.WaitForExit();
        Check(audioProbe.ExitCode == 0, "preserved audio stream is missing");

        request["plan_version"] = "2";
        foreach (var clip in (JsonArray)request["clips"]!)
        {
            ((JsonObject)clip!).Remove("trim_start_ms");
            ((JsonObject)clip).Remove("trim_end_ms");
        }
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        Check(PlatformFfmpegTaskPlan.Execute(root, task) == 0,
            "two complete MP4 files did not produce a video");
        var actualFfprobe = (Environment.GetEnvironmentVariable("PATH") ?? "")
            .Split(Path.PathSeparator)
            .Select(directory => Path.Combine(directory, "ffprobe"))
            .FirstOrDefault(File.Exists);
        if (actualFfprobe is not null)
        {
            var probe = Process.Start(new ProcessStartInfo(actualFfprobe)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                ArgumentList = {
                    "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    Path.Combine(task, "final.mp4"),
                },
            })!;
            var durationText = probe.StandardOutput.ReadToEnd();
            probe.WaitForExit();
            Check(probe.ExitCode == 0 && double.TryParse(durationText,
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out var duration)
                && duration >= 1.9 && duration <= 2.2,
                "complete-file output did not retain both one-second clips");
        }
        request["clips"]![0]!["trim_start_ms"] = 500;
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        Check(PlatformFfmpegTaskPlan.Execute(root, task) == 0,
            "open-ended start trim was rejected");
        if (actualFfprobe is not null)
        {
            var probe = Process.Start(new ProcessStartInfo(actualFfprobe)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                ArgumentList = {
                    "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    Path.Combine(task, "final.mp4"),
                },
            })!;
            var durationText = probe.StandardOutput.ReadToEnd();
            probe.WaitForExit();
            Check(probe.ExitCode == 0 && double.TryParse(durationText,
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out var duration)
                && duration >= 1.3 && duration <= 1.7,
                "open-ended start trim did not retain the remainder");
        }
        ((JsonObject)request["clips"]![0]!).Remove("trim_start_ms");
        request["clips"]![0]!["trim_end_ms"] = 500;
        File.WriteAllText(Path.Combine(task, "input.json"), request.ToJsonString());
        Check(PlatformFfmpegTaskPlan.Execute(root, task) == 0,
            "open-ended end trim was rejected");
    }

    public static async Task Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "dclaw-helper-regression-" + Guid.NewGuid());
        try
        {
            var handler = new AssetsHandler();
            var runtime = new HelperRuntime("unused", new HelperConfig(
                "wss://unused", "device", null, null, "test"),
                root, new HttpClient(handler));
            CheckPlatformFfmpegTaskPlan(root);
            var taskId = Guid.NewGuid().ToString("N");
            var taskRoot = HelperPathSafety.TaskRoot(root, "test", taskId);
            Directory.CreateDirectory(Path.Combine(taskRoot, "res"));
            File.WriteAllText(Path.Combine(taskRoot, "res", "clip_01.mp4.download"), "partial");
            var result = await Run(runtime, root, taskId,
                Asset("one", "clip_01", "first", 0) + "," +
                Asset("two", "clip_02", "second", 1));
            Check(result.GetProperty("event_type").GetString() == "completed",
                "multi-asset localization failed after input document disposal");
            Check(File.ReadAllText(Path.Combine(taskRoot, "res", "clip_01.mp4")) == "first",
                "partial download was not replaced");
            Check(File.ReadAllText(Path.Combine(taskRoot, "res", "clip_02.mp4")) == "second",
                "second asset missing");
            Check(File.Exists(Path.Combine(taskRoot, "assets.json")), "manifest missing");
            using (var manifest = JsonDocument.Parse(
                File.ReadAllText(Path.Combine(taskRoot, "assets.json"))))
            {
                var entries = manifest.RootElement.GetProperty("assets").EnumerateArray().ToArray();
                Check(entries.Length == 2, "manifest asset count incorrect");
                Check(entries[0].GetProperty("sha256").GetString() ==
                      Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("first"))).ToLowerInvariant(),
                    "first asset digest incorrect");
                Check(entries[1].GetProperty("sha256").GetString() ==
                      Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("second"))).ToLowerInvariant(),
                    "second asset digest incorrect");
            }

            var scope = new {
                tenant_id = "tenant", user_id = "user", session_id = "session",
                agent_id = "agent", installation_id = "install",
                release_id = "release", invocation_id = "invocation",
            };
            var bindInput = JsonSerializer.Serialize(new {
                type = "aigc.assets.bind", request_id = "bind-two", source_task_id = taskId,
                source_agent_name = "test", scope,
                files = result.GetProperty("payload").GetProperty("files"),
            });
            var bindMethod = typeof(HelperRuntime).GetMethod(
                "BindAigcAssetsAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var handleBind = typeof(HelperRuntime).GetMethod(
                "HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using (var document = JsonDocument.Parse(bindInput))
                await (Task)handleBind.Invoke(runtime, new object[] {
                    document.RootElement, CancellationToken.None,
                })!;
            for (var attempt = 0; attempt < 200 && !File.Exists(Path.Combine(
                root, "Outbox", "response-bind-two.json")); attempt++)
                await Task.Delay(25);
            var bindResponse = JsonNode.Parse(File.ReadAllText(Path.Combine(
                root, "Outbox", "response-bind-two.json")))!.AsObject();
            Check(bindResponse["status"]!.GetValue<string>() == "bound",
                "two localized files could not be bound");
            var bound = bindResponse["files"]!.AsArray();
            Check(bound.Count == 2
                && bound[0]!["slot"]!.GetValue<string>() == "clip_01"
                && bound[1]!["slot"]!.GetValue<string>() == "clip_02",
                "binding order was not preserved");
            var lifetimeBindings = new JsonObject
            {
                ["clip_01"] = new JsonObject
                {
                    ["local_file_ref"] = bound[0]!["file"]!["local_file_ref"]!.DeepClone(),
                    ["access"] = "read",
                },
                ["clip_02"] = new JsonObject
                {
                    ["local_file_ref"] = "lfr_missing",
                    ["access"] = "read",
                },
            };
            var startTaskId = Guid.NewGuid().ToString("N");
            var startMessage = new JsonObject
            {
                ["type"] = "task.start",
                ["task"] = new JsonObject
                {
                    ["task_id"] = startTaskId,
                    ["task_root_name"] = "test",
                    ["capability_id"] = PlatformFfmpegTaskPlan.CapabilityId,
                    ["input"] = new JsonObject(),
                    ["local_file_bindings"] = lifetimeBindings.DeepClone(),
                    ["scope"] = JsonSerializer.SerializeToNode(scope),
                },
            };
            var startEvent = await RunTaskMessage(
                runtime, root, startTaskId, startMessage.ToJsonString());
            Check(startEvent.GetProperty("payload").GetProperty("code").GetString()
                == "LOCAL_FILE_REF.RESOLVE_FAILED",
                "task.start used a disposed input document");

            var continueTaskId = Guid.NewGuid().ToString("N");
            var continueRoot = HelperPathSafety.TaskRoot(root, "test", continueTaskId);
            Directory.CreateDirectory(continueRoot);
            File.WriteAllText(Path.Combine(continueRoot, "agent.name"), "test");
            File.WriteAllText(Path.Combine(continueRoot, "capability.id"),
                PlatformFfmpegTaskPlan.CapabilityId);
            var continueMessage = new JsonObject
            {
                ["type"] = "task.continue",
                ["task_id"] = continueTaskId,
                ["input"] = new JsonObject(),
                ["local_file_bindings"] = lifetimeBindings.DeepClone(),
                ["scope"] = JsonSerializer.SerializeToNode(scope),
            };
            var continueEvent = await RunTaskMessage(
                runtime, root, continueTaskId, continueMessage.ToJsonString());
            Check(continueEvent.GetProperty("payload").GetProperty("code").GetString()
                == "LOCAL_FILE_REF.RESOLVE_FAILED",
                "task.continue used a disposed input document");
            var nextRoot = HelperPathSafety.TaskRoot(root, "test", "next-task");
            Directory.CreateDirectory(nextRoot);
            var bindings = new JsonObject();
            foreach (var item in bound)
                bindings[item!["slot"]!.GetValue<string>()] = new JsonObject {
                    ["local_file_ref"] = item["file"]!["local_file_ref"]!.DeepClone(),
                    ["access"] = "read",
                };
            var stageMethod = typeof(HelperRuntime).GetMethod(
                "StageLocalFileBindingsAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using (var bindingDocument = JsonDocument.Parse(bindings.ToJsonString()))
            using (var scopeDocument = JsonDocument.Parse(JsonSerializer.Serialize(scope)))
            {
                var nextInput = new JsonObject();
                await (Task)stageMethod.Invoke(runtime, new object[] {
                    nextRoot, nextInput, bindingDocument.RootElement,
                    scopeDocument.RootElement, CancellationToken.None,
                })!;
                Check(nextInput.Count == 2 && nextInput.ContainsKey("clip_01")
                    && nextInput.ContainsKey("clip_02"),
                    "next task did not accept both file bindings");
            }
            File.AppendAllText(Path.Combine(taskRoot, "res", "clip_01.mp4"), "changed");
            var changedInput = bindInput.Replace("bind-two", "bind-changed");
            using (var document = JsonDocument.Parse(changedInput))
                await (Task)bindMethod.Invoke(runtime, new object[] {
                    document.RootElement, CancellationToken.None,
                })!;
            var changedResponse = JsonNode.Parse(File.ReadAllText(Path.Combine(
                root, "Outbox", "response-bind-changed.json")))!.AsObject();
            Check(changedResponse["error_code"]!.GetValue<string>() == "LOCAL_SOURCE.FILE_CHANGED",
                "changed file was accepted");
            File.WriteAllText(Path.Combine(taskRoot, "res", "clip_01.mp4"), "first");
            File.Delete(Path.Combine(taskRoot, "res", "clip_02.mp4"));
            var missingInput = bindInput.Replace("bind-two", "bind-missing");
            using (var document = JsonDocument.Parse(missingInput))
                await (Task)bindMethod.Invoke(runtime, new object[] {
                    document.RootElement, CancellationToken.None,
                })!;
            var missingResponse = JsonNode.Parse(File.ReadAllText(Path.Combine(
                root, "Outbox", "response-bind-missing.json")))!.AsObject();
            Check(missingResponse["error_code"]!.GetValue<string>() == "LOCAL_SOURCE.FILE_MISSING",
                "missing file was accepted");

            handler.Fail = true;
            var failed = await Run(runtime, root, Guid.NewGuid().ToString("N"),
                Asset("one", "clip_01", "first", 0));
            Check(failed.GetProperty("event_type").GetString() == "failed",
                "download failure did not terminate");
            Check(failed.GetProperty("payload").GetProperty("phase").GetString() == "download_transfer",
                "download failure phase was not recorded");

            var invalid = await Run(runtime, root, Guid.NewGuid().ToString("N"), "");
            Check(invalid.GetProperty("event_type").GetString() == "failed",
                "empty asset list was not rejected");
            Check(invalid.GetProperty("payload").GetProperty("code").GetString()
                  == "AIGC_LOCALIZE_INVALID_INPUT", "invalid input code missing");

            var collision = await Run(runtime, root, Guid.NewGuid().ToString("N"),
                Asset("one", "clip_01", "first", 0) + "," +
                Asset("two", "clip_01", "second", 1));
            Check(collision.GetProperty("event_type").GetString() == "failed",
                "duplicate output path was not rejected");
            Console.WriteLine("Helper regression passed: localization, prior-output binding, disposed task dispatch, next-task input, changed file, download error and invalid input");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }
}
