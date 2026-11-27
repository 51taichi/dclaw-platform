using System.Text;

internal static class HelperPathSafety
{
    private static readonly HashSet<string> WindowsReservedNames = new(
        new[] { "CON", "PRN", "AUX", "NUL", "CLOCK$" }
            .Concat(Enumerable.Range(1, 9).SelectMany(number => new[] {
                $"COM{number}", $"LPT{number}",
            })),
        StringComparer.OrdinalIgnoreCase);

    internal static string SafeName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars().ToHashSet();
        invalid.Add(Path.DirectorySeparatorChar);
        invalid.Add(Path.AltDirectorySeparatorChar);
        var builder = new StringBuilder(value.Length);
        foreach (var character in value)
            builder.Append(
                invalid.Contains(character) || char.IsControl(character)
                    ? '_'
                    : character);
        var normalized = builder.ToString().Trim().TrimEnd('.', ' ');
        if (string.IsNullOrWhiteSpace(normalized) || normalized is "." or "..")
            return "unnamed";
        normalized = normalized[..Math.Min(normalized.Length, 80)];
        var deviceName = normalized.Split('.')[0];
        return WindowsReservedNames.Contains(deviceName)
            ? "_" + normalized
            : normalized;
    }

    internal static string TaskRoot(string helperRoot, string agentName, string taskId)
    {
        var tasksRoot = Path.GetFullPath(Path.Combine(helperRoot, "Tasks"));
        var path = Path.GetFullPath(Path.Combine(
            tasksRoot,
            SafeName(agentName),
            SafeName(taskId)));
        var prefix = tasksRoot.TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("task path escapes Tasks root");
        return path;
    }
}
