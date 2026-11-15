using System.Net;
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

    private static void Check(bool condition, string reason)
    {
        if (!condition) throw new Exception(reason);
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
            Console.WriteLine("Helper regression passed: localization, prior-output binding, next-task input, changed file, download error and invalid input");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }
}
