using System.Runtime.InteropServices;

namespace DClaw.LocalHelper;

internal static class LocalAssistantUi
{
    private const string BallClass = "DClawLocalAssistantBall";
    private const string DashboardClass = "DClawLocalAssistantDashboard";
    private const int BallSize = 60;
    private const int DashboardWidth = 320;
    private const int DashboardHeight = 390;
    private const int TaskCardHeight = 120;
    private const int ListTop = 104;
    private const int MaxVisibleRows = 2;

    private const uint WsPopup = 0x80000000;
    private const uint WsExTopmost = 0x00000008;
    private const uint WsExToolWindow = 0x00000080;
    private const int SwHide = 0;
    private const int SwShow = 5;
    private const int SwShowNoActivate = 4;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoActivate = 0x0010;
    private const uint WmDestroy = 0x0002;
    private const uint WmClose = 0x0010;
    private const uint WmPaint = 0x000F;
    private const uint WmTimer = 0x0113;
    private const uint WmLButtonDown = 0x0201;
    private const uint WmLButtonUp = 0x0202;
    private const uint WmLButtonDblClk = 0x0203;
    private const uint WmMouseMove = 0x0200;
    private const uint WmRButtonUp = 0x0205;
    private const uint WmMouseWheel = 0x020A;
    private const uint WmActivate = 0x0006;
    private const int ColorWindow = 5;
    private const int IdcArrow = 32512;
    private const int Transparent = 1;
    private const uint DtLeft = 0x0000;
    private const uint DtCenter = 0x0001;
    private const uint DtVCenter = 0x0004;
    private const uint DtSingleLine = 0x0020;
    private const uint DtEndEllipsis = 0x8000;
    private const uint MfString = 0x0000;
    private const uint MfSeparator = 0x0800;
    private const uint TpmReturnCmd = 0x0100;
    private const uint TpmRightButton = 0x0002;
    private const int SpiGetWorkArea = 0x0030;
    private const int MenuTasks = 1001;
    private const int MenuDirectory = 1002;
    private const int MenuExit = 1003;

    private static readonly WndProc WindowProcedure = HandleWindowMessage;
    private static string _root = string.Empty;
    private static Func<bool> _connected = () => false;
    private static IntPtr _ball;
    private static IntPtr _dashboard;
    private static bool _dragging;
    private static bool _dragged;
    private static bool _taskPage;
    private static bool _outputPage;
    private static Point _dragCursor;
    private static Point _dragWindow;
    private static IReadOnlyList<LocalTaskItem> _tasks = Array.Empty<LocalTaskItem>();
    private static int _selectedTask;
    private static int _selectedOutput;
    private static int _taskScroll;
    private static int _outputScroll;
    private static IntPtr _logo;
    private static IntPtr _gdiplusToken;

    internal static void Run(string root, Func<bool> connected)
    {
        if (!OperatingSystem.IsWindows()) return;
        _root = root;
        _connected = connected;
        Directory.CreateDirectory(Path.Combine(root, "Tasks"));
        LoadLogo(root);
        var instance = GetModuleHandle(null);
        RegisterWindowClass(BallClass, instance, (uint)(ColorWindow + 1));
        RegisterWindowClass(DashboardClass, instance, (uint)(ColorWindow + 1));

        SystemParametersInfo(SpiGetWorkArea, 0, out var workArea, 0);
        _ball = CreateWindowEx(
            WsExTopmost | WsExToolWindow,
            BallClass,
            "DClaw 本地助手",
            WsPopup,
            workArea.Right - BallSize - 24,
            workArea.Bottom - BallSize - 16,
            BallSize,
            BallSize,
            IntPtr.Zero,
            IntPtr.Zero,
            instance,
            IntPtr.Zero);
        _dashboard = CreateWindowEx(
            WsExTopmost | WsExToolWindow,
            DashboardClass,
            "DClaw 本地助手",
            WsPopup,
            workArea.Left + Math.Max(0, (workArea.Width - DashboardWidth) / 2),
            workArea.Top + Math.Max(0, (workArea.Height - DashboardHeight) / 2),
            DashboardWidth,
            DashboardHeight,
            IntPtr.Zero,
            IntPtr.Zero,
            instance,
            IntPtr.Zero);
        if (_ball == IntPtr.Zero || _dashboard == IntPtr.Zero)
            throw new InvalidOperationException("无法创建本地助手窗口");
        SetWindowRgn(_ball, CreateEllipticRgn(0, 0, BallSize, BallSize), true);
        SetWindowRgn(_dashboard, CreateRoundRectRgn(0, 0, DashboardWidth, DashboardHeight, 48, 48), true);
        SetTimer(_ball, 1, 2000, IntPtr.Zero);
        SetTimer(_dashboard, 2, 3000, IntPtr.Zero);
        ReloadTasks();
        ShowWindow(_ball, SwShowNoActivate);
        UpdateWindow(_ball);
        while (GetMessage(out var message, IntPtr.Zero, 0, 0) > 0)
        {
            TranslateMessage(ref message);
            DispatchMessage(ref message);
        }
        if (_logo != IntPtr.Zero) GdipDisposeImage(_logo);
        if (_gdiplusToken != IntPtr.Zero) GdiplusShutdown(_gdiplusToken);
    }

    private static void RegisterWindowClass(string name, IntPtr instance, uint background)
    {
        var windowClass = new WindowClass
        {
            Size = (uint)Marshal.SizeOf<WindowClass>(),
            Style = 0x0008,
            WindowProcedure = WindowProcedure,
            Instance = instance,
            Cursor = LoadCursor(IntPtr.Zero, (IntPtr)IdcArrow),
            Background = background <= 31
                ? (IntPtr)background
                : CreateSolidBrush(background),
            ClassName = name,
        };
        if (RegisterClassEx(ref windowClass) == 0
            && Marshal.GetLastWin32Error() != 1410)
            throw new InvalidOperationException($"无法注册本地助手窗口: {name}");
    }

    private static IntPtr HandleWindowMessage(
        IntPtr window,
        uint message,
        UIntPtr wParam,
        IntPtr lParam)
    {
        try
        {
            return window == _ball
                ? HandleBallMessage(window, message, wParam, lParam)
                : HandleDashboardMessage(window, message, wParam, lParam);
        }
        catch
        {
            return DefWindowProc(window, message, wParam, lParam);
        }
    }

    private static IntPtr HandleBallMessage(
        IntPtr window,
        uint message,
        UIntPtr wParam,
        IntPtr lParam)
    {
        switch (message)
        {
            case WmPaint:
                PaintBall(window);
                return IntPtr.Zero;
            case WmTimer:
                InvalidateRect(window, IntPtr.Zero, false);
                return IntPtr.Zero;
            case WmLButtonDown:
                GetCursorPos(out _dragCursor);
                GetWindowRect(window, out var bounds);
                _dragWindow = new Point(bounds.Left, bounds.Top);
                _dragged = false;
                _dragging = true;
                SetCapture(window);
                return IntPtr.Zero;
            case WmMouseMove when _dragging:
                GetCursorPos(out var cursor);
                var dx = cursor.X - _dragCursor.X;
                var dy = cursor.Y - _dragCursor.Y;
                if (Math.Abs(dx) + Math.Abs(dy) > 4) _dragged = true;
                SetWindowPos(
                    window,
                    new IntPtr(-1),
                    _dragWindow.X + dx,
                    _dragWindow.Y + dy,
                    0,
                    0,
                    SwpNoSize | SwpNoActivate);
                return IntPtr.Zero;
            case WmLButtonUp:
                _dragging = false;
                ReleaseCapture();
                if (!_dragged) ToggleDashboard();
                return IntPtr.Zero;
            case WmRButtonUp:
                ShowContextMenu(window);
                return IntPtr.Zero;
            case WmDestroy:
                PostQuitMessage(0);
                return IntPtr.Zero;
            default:
                return DefWindowProc(window, message, wParam, lParam);
        }
    }

    private static IntPtr HandleDashboardMessage(
        IntPtr window,
        uint message,
        UIntPtr wParam,
        IntPtr lParam)
    {
        switch (message)
        {
            case WmPaint:
                PaintDashboard(window);
                return IntPtr.Zero;
            case WmTimer:
                ReloadTasks();
                InvalidateRect(window, IntPtr.Zero, true);
                return IntPtr.Zero;
            case WmClose:
                ShowWindow(window, SwHide);
                return IntPtr.Zero;
            case WmLButtonUp:
                HandleDashboardClick(window, LowWord(lParam), HighWord(lParam), false);
                return IntPtr.Zero;
            case WmLButtonDblClk:
                HandleDashboardClick(window, LowWord(lParam), HighWord(lParam), true);
                return IntPtr.Zero;
            case WmMouseWheel:
                var delta = unchecked((short)(((ulong)wParam.ToUInt64() >> 16) & 0xffff));
                ScrollDashboard(delta > 0 ? -1 : 1);
                InvalidateRect(window, IntPtr.Zero, true);
                return IntPtr.Zero;
            case WmActivate when (wParam.ToUInt64() & 0xffff) == 0:
                ShowWindow(window, SwHide);
                return IntPtr.Zero;
            default:
                return DefWindowProc(window, message, wParam, lParam);
        }
    }

    private static void PaintBall(IntPtr window)
    {
        var dc = BeginPaint(window, out var paint);
        try
        {
            var attention = AttentionState();
            using var ring = new GdiObject(CreateSolidBrush(attention.Color));
            using var white = new GdiObject(CreateSolidBrush(ColorRef(255, 255, 255)));
            using var status = new GdiObject(CreateSolidBrush(attention.Color));
            var oldPen = SelectObject(dc, GetStockObject(8));
            var oldBrush = SelectObject(dc, ring.Handle);
            Ellipse(dc, 1, 1, BallSize - 1, BallSize - 1);
            SelectObject(dc, white.Handle);
            Ellipse(dc, 5, 5, BallSize - 5, BallSize - 5);
            DrawLogo(dc, 6, 6, BallSize - 12);
            Ellipse(dc, BallSize - 18, BallSize - 18, BallSize - 2, BallSize - 2);
            SelectObject(dc, status.Handle);
            Ellipse(dc, BallSize - 16, BallSize - 16, BallSize - 4, BallSize - 4);
            SelectObject(dc, oldBrush);
            SelectObject(dc, oldPen);
        }
        finally
        {
            EndPaint(window, ref paint);
        }
    }

    private static void PaintDashboard(IntPtr window)
    {
        var dc = BeginPaint(window, out var paint);
        try
        {
            using var white = new GdiObject(CreateSolidBrush(ColorRef(255, 255, 255)));
            var client = new Rect(0, 0, DashboardWidth, DashboardHeight);
            FillRect(dc, ref client, white.Handle);
            SetBkMode(dc, Transparent);
            if (_outputPage) PaintOutputPage(dc);
            else if (_taskPage) PaintTaskPage(dc);
            else PaintMainPage(dc);
        }
        finally
        {
            EndPaint(window, ref paint);
        }
    }

    private static void PaintMainPage(IntPtr dc)
    {
        DrawLogo(dc, 20, 20, 38);
        DrawLabel(dc, "DClaw本地助手", 66, 18, 190, 26, 19, 600, ColorRef(25, 29, 36));
        DrawLabel(dc, $"版本 {HelperMetadata.Version}", 66, 44, 185, 18, 12, 400, ColorRef(107, 114, 128));
        DrawRounded(dc, new Rect(264, 20, 302, 58), 38, ColorRef(239, 244, 255));
        DrawGlyph(dc, "\uE896", 264, 20, 38, 38, 18, ColorRef(37, 99, 235));
        DrawRounded(dc, new Rect(18, 76, 302, 124), 12, ColorRef(243, 247, 255));
        var attention = AttentionState();
        using var status = new GdiObject(CreateSolidBrush(attention.Color));
        var oldPen = SelectObject(dc, GetStockObject(8));
        var oldBrush = SelectObject(dc, status.Handle);
        Ellipse(dc, 31, 95, 41, 105);
        SelectObject(dc, oldBrush);
        SelectObject(dc, oldPen);
        DrawLabel(dc, attention.Label, 51, 86, 229, 28,
            14, 400, ColorRef(55, 65, 81));
        DrawRounded(dc, new Rect(39, 205, 97, 263), 58, ColorRef(47, 52, 64));
        DrawRounded(dc, new Rect(131, 205, 189, 263), 58, ColorRef(47, 52, 64));
        DrawRounded(dc, new Rect(223, 205, 281, 263), 58, ColorRef(159, 18, 57));
        DrawLabel(dc, "☷", 39, 205, 58, 58, 24, 400, ColorRef(255, 255, 255), center: true);
        DrawLabel(dc, "⌂", 131, 205, 58, 58, 24, 400, ColorRef(255, 255, 255), center: true);
        DrawLabel(dc, "×", 223, 205, 58, 58, 24, 400, ColorRef(255, 255, 255), center: true);
        DrawLabel(dc, "任务", 39, 271, 58, 22, 13, 400, ColorRef(25, 29, 36), center: true);
        DrawLabel(dc, "目录", 131, 271, 58, 22, 13, 400, ColorRef(25, 29, 36), center: true);
        DrawLabel(dc, "退出", 223, 271, 58, 22, 13, 400, ColorRef(25, 29, 36), center: true);
        DrawRounded(dc, new Rect(78, 199, 99, 219), 20, ColorRef(37, 99, 235));
        DrawLabel(dc, _tasks.Count.ToString(), 78, 199, 21, 20, 11, 400,
            ColorRef(255, 255, 255), center: true);
    }

    private static void PaintTaskPage(IntPtr dc)
    {
        DrawRounded(dc, new Rect(18, 18, 56, 56), 38, ColorRef(239, 244, 255));
        DrawGlyph(dc, "\uE72B", 18, 18, 38, 38, 18, ColorRef(37, 99, 235));
        DrawLabel(dc, "任务中心", 70, 18, 180, 38, 20, 600, ColorRef(25, 29, 36), center: true);
        DrawLabel(dc, $"共 {_tasks.Count} 个本地任务", 18, 70, 200, 28, 12, 400,
            ColorRef(107, 114, 128));
        DrawRounded(dc, new Rect(239, 70, 302, 98), 8, ColorRef(37, 99, 235));
        DrawLabel(dc, "刷新", 239, 70, 63, 28, 12, 400, ColorRef(255, 255, 255), center: true);
        if (_tasks.Count == 0)
            DrawLabel(dc, "暂无任务", 18, 172, 284, 30, 14, 400,
                ColorRef(107, 114, 128), center: true);
        for (var visible = 0; visible < MaxVisibleRows; visible++)
        {
            var index = _taskScroll + visible;
            if (index >= _tasks.Count) break;
            var task = _tasks[index];
            var top = ListTop + visible * (TaskCardHeight + 10);
            DrawRounded(dc, new Rect(18, top, 302, top + TaskCardHeight), 14,
                ColorRef(249, 250, 251), ColorRef(229, 231, 235));
            DrawLabel(dc, task.AgentName, 31, top + 10, 225, 24, 14, 600,
                ColorRef(25, 29, 36));
            using var status = new GdiObject(CreateSolidBrush(StatusColor(task.Status)));
            var oldPen = SelectObject(dc, GetStockObject(8));
            var oldBrush = SelectObject(dc, status.Handle);
            Ellipse(dc, 274, top + 15, 286, top + 27);
            SelectObject(dc, oldBrush);
            SelectObject(dc, oldPen);
            var shortId = task.TaskId[..Math.Min(8, task.TaskId.Length)];
            DrawLabel(dc, $"任务 {shortId} · {task.UpdatedAt.ToLocalTime():MM-dd HH:mm}",
                31, top + 37, 252, 18, 11, 400, ColorRef(107, 114, 128));
            DrawLabel(dc, StatusText(task.Status), 31, top + 58, 220, 17, 11, 400,
                StatusColor(task.Status));
            if (task.Outputs.Count > 0)
            {
                DrawTaskAction(dc, new Rect(31, top + 83, 111, top + 111), "打开成品");
                DrawTaskAction(dc, new Rect(117, top + 83, 197, top + 111), "成品目录");
            }
            DrawTaskAction(dc, new Rect(task.Outputs.Count > 0 ? 203 : 31, top + 83,
                task.Outputs.Count > 0 ? 289 : 133, top + 111), "任务目录");
        }
    }

    private static void DrawTaskAction(IntPtr dc, Rect bounds, string label)
    {
        DrawRounded(dc, bounds, 8, ColorRef(243, 244, 246), ColorRef(229, 231, 235));
        DrawLabel(dc, label, bounds.Left, bounds.Top, bounds.Width, bounds.Height,
            11, 400, ColorRef(55, 65, 81), center: true);
    }

    private static void PaintOutputPage(IntPtr dc)
    {
        DrawRounded(dc, new Rect(18, 18, 56, 56), 38, ColorRef(239, 244, 255));
        DrawGlyph(dc, "\uE72B", 18, 18, 38, 38, 18, ColorRef(37, 99, 235));
        DrawLabel(dc, "任务输出", 70, 18, 180, 38, 20, 600,
            ColorRef(25, 29, 36), center: true);
        var task = SelectedTask();
        if (task is null) return;
        DrawLabel(dc, task.AgentName, 18, 68, 284, 24, 14, 600, ColorRef(55, 65, 81));
        DrawLabel(dc, $"{task.Outputs.Count} 个文件", 18, 91, 284, 18,
            11, 400, ColorRef(107, 114, 128));
        if (task.Outputs.Count == 0)
            DrawLabel(dc, "暂无输出文件", 18, 190, 284, 30,
                14, 400, ColorRef(107, 114, 128), center: true);
        for (var visible = 0; visible < 4; visible++)
        {
            var index = _outputScroll + visible;
            if (index >= task.Outputs.Count) break;
            var output = task.Outputs[index];
            var top = 118 + visible * 54;
            DrawRounded(dc, new Rect(18, top, 302, top + 48), 8,
                index == _selectedOutput ? ColorRef(239, 244, 255) : ColorRef(249, 250, 251),
                ColorRef(229, 231, 235));
            DrawLabel(dc, output.Name, 29, top + 3, 260, 23, 12, 500, ColorRef(55, 65, 81));
            DrawLabel(dc, FormatSize(output.SizeBytes), 29, top + 25, 260, 17,
                11, 400, ColorRef(107, 114, 128));
        }
        DrawTaskAction(dc, new Rect(18, 344, 151, 372), "打开文件");
        DrawTaskAction(dc, new Rect(159, 344, 302, 372), "打开所在目录");
    }

    private static void DrawRounded(IntPtr dc, Rect bounds, int radius, uint fill, uint? border = null)
    {
        using var brush = new GdiObject(CreateSolidBrush(fill));
        using var pen = new GdiObject(CreatePen(0, 1, border ?? fill));
        var oldBrush = SelectObject(dc, brush.Handle);
        var oldPen = SelectObject(dc, pen.Handle);
        RoundRect(dc, bounds.Left, bounds.Top, bounds.Right, bounds.Bottom, radius * 2, radius * 2);
        SelectObject(dc, oldPen);
        SelectObject(dc, oldBrush);
    }

    private static void DrawGlyph(IntPtr dc, string glyph, int x, int y,
        int width, int height, int size, uint color)
    {
        using var font = new GdiObject(CreateFont(-size, 0, 0, 0, 400,
            0, 0, 0, 1, 0, 0, 5, 0, "Segoe MDL2 Assets"));
        var oldFont = SelectObject(dc, font.Handle);
        SetTextColor(dc, color);
        var bounds = new Rect(x, y, x + width, y + height);
        DrawText(dc, glyph, -1, ref bounds, DtCenter | DtVCenter | DtSingleLine);
        SelectObject(dc, oldFont);
    }

    private static void LoadLogo(string root)
    {
        try
        {
            using var resource = typeof(LocalAssistantUi).Assembly.GetManifestResourceStream(
                "DClaw.LocalHelper.Assets.DClaw-Bot-icon.png");
            if (resource is null) return;
            var logoPath = Path.Combine(root, "assistant-logo.png");
            using (var output = File.Create(logoPath)) resource.CopyTo(output);
            var startup = new GdiplusStartupInput { Version = 1 };
            if (GdiplusStartup(out _gdiplusToken, ref startup, IntPtr.Zero) != 0) return;
            if (GdipLoadImageFromFile(logoPath, out _logo) != 0) _logo = IntPtr.Zero;
        }
        catch (IOException)
        {
            _logo = IntPtr.Zero;
        }
    }

    private static void DrawLogo(IntPtr dc, int x, int y, int size)
    {
        if (_logo == IntPtr.Zero)
        {
            DrawRounded(dc, new Rect(x, y, x + size, y + size), size / 2, ColorRef(242, 91, 43));
            DrawLabel(dc, "D", x, y, size, size, size / 2, 700,
                ColorRef(255, 255, 255), center: true);
            return;
        }
        if (GdipCreateFromHDC(dc, out var graphics) != 0) return;
        try
        {
            GdipSetInterpolationMode(graphics, 7);
            GdipSetSmoothingMode(graphics, 4);
            GdipSetPixelOffsetMode(graphics, 4);
            if (GdipCreatePath(0, out var path) != 0) return;
            try
            {
                GdipAddPathEllipseI(path, x, y, size, size);
                GdipSetClipPath(graphics, path, 0);
                GdipDrawImageRectI(graphics, _logo, x, y, size, size);
            }
            finally
            {
                GdipDeletePath(path);
            }
        }
        finally
        {
            GdipDeleteGraphics(graphics);
        }
    }

    private static void HandleDashboardClick(IntPtr window, int x, int y, bool doubleClick)
    {
        if (_outputPage)
        {
            if (Contains(new Rect(18, 18, 56, 56), x, y)) _outputPage = false;
            else if (y >= 118 && y < 334)
            {
                var row = (y - 118) / 54;
                var index = _outputScroll + row;
                var task = SelectedTask();
                if (task is not null && index < task.Outputs.Count && y < 118 + row * 54 + 48)
                {
                    _selectedOutput = index;
                    if (doubleClick) TaskHistory.OpenFile(task.Outputs[index].FullPath);
                }
            }
            else if (Contains(new Rect(18, 344, 151, 372), x, y)) OpenSelectedOutput(false);
            else if (Contains(new Rect(159, 344, 302, 372), x, y)) OpenSelectedOutput(true);
            InvalidateRect(window, IntPtr.Zero, true);
            return;
        }
        if (!_taskPage)
        {
            if (Contains(new Rect(264, 20, 302, 58), x, y))
                MessageBox(window, "本地助手由 DClaw 客户端自动更新。", "DClaw本地助手", 0);
            else if (Contains(new Rect(39, 205, 97, 263), x, y))
            {
                _taskPage = true;
                ReloadTasks();
            }
            else if (Contains(new Rect(131, 205, 189, 263), x, y))
                TaskHistory.OpenDirectory(Path.Combine(_root, "Tasks"));
            else if (Contains(new Rect(223, 205, 281, 263), x, y))
                DestroyWindow(_ball);
            InvalidateRect(window, IntPtr.Zero, true);
            return;
        }
        if (Contains(new Rect(18, 18, 56, 56), x, y))
            _taskPage = false;
        else if (Contains(new Rect(239, 70, 302, 98), x, y))
            ReloadTasks();
        else if (y >= ListTop && y < ListTop + MaxVisibleRows * (TaskCardHeight + 10))
        {
            var row = (y - ListTop) / (TaskCardHeight + 10);
            var top = ListTop + row * (TaskCardHeight + 10);
            var index = _taskScroll + row;
            if (index < _tasks.Count && y < top + TaskCardHeight)
            {
                var task = _tasks[index];
                if (y >= top + 83 && y < top + 111)
                {
                    if (task.Outputs.Count > 0 && x >= 31 && x < 111)
                        TaskHistory.OpenFile(task.Outputs[0].FullPath);
                    else if (task.Outputs.Count > 0 && x >= 117 && x < 197)
                        TaskHistory.OpenDirectory(task.Outputs[0].FullPath, selectFile: true);
                    else if (x >= (task.Outputs.Count > 0 ? 203 : 31) && x < (task.Outputs.Count > 0 ? 289 : 133))
                        TaskHistory.OpenDirectory(task.TaskRoot);
                }
                else
                {
                    _selectedTask = index;
                    _selectedOutput = 0;
                    _outputScroll = 0;
                    _outputPage = true;
                }
            }
        }
        InvalidateRect(window, IntPtr.Zero, true);
    }

    private static void ScrollDashboard(int direction)
    {
        if (_outputPage)
        {
            var count = SelectedTask()?.Outputs.Count ?? 0;
            _outputScroll = Math.Clamp(_outputScroll + direction, 0,
                Math.Max(0, count - 4));
        }
        else if (_taskPage)
            _taskScroll = Math.Clamp(_taskScroll + direction, 0,
                Math.Max(0, _tasks.Count - MaxVisibleRows));
    }

    private static void ToggleDashboard()
    {
        if (IsWindowVisible(_dashboard))
        {
            ShowWindow(_dashboard, SwHide);
            return;
        }
        _taskPage = false;
        _outputPage = false;
        ReloadTasks();
        GetWindowRect(_ball, out var ball);
        SystemParametersInfo(SpiGetWorkArea, 0, out var workArea, 0);
        var x = ball.Left - DashboardWidth - 14;
        if (x < workArea.Left) x = ball.Right + 14;
        var y = ball.Top + BallSize / 2 - DashboardHeight / 2;
        SetWindowPos(_dashboard, new IntPtr(-1),
            Math.Clamp(x, workArea.Left + 8, Math.Max(workArea.Left + 8, workArea.Right - DashboardWidth - 8)),
            Math.Clamp(y, workArea.Top + 8, Math.Max(workArea.Top + 8, workArea.Bottom - DashboardHeight - 8)),
            0, 0, SwpNoSize);
        ShowWindow(_dashboard, SwShow);
        SetForegroundWindow(_dashboard);
        InvalidateRect(_dashboard, IntPtr.Zero, true);
    }

    private static void ShowContextMenu(IntPtr owner)
    {
        var menu = CreatePopupMenu();
        try
        {
            AppendMenu(menu, MfString, MenuTasks, "本地任务");
            AppendMenu(menu, MfString, MenuDirectory, "打开任务目录");
            AppendMenu(menu, MfSeparator, 0, string.Empty);
            AppendMenu(menu, MfString, MenuExit, "退出本地助手");
            GetCursorPos(out var cursor);
            SetForegroundWindow(owner);
            var command = TrackPopupMenu(
                menu,
                TpmReturnCmd | TpmRightButton,
                cursor.X,
                cursor.Y,
                0,
                owner,
                IntPtr.Zero);
            if (command == MenuTasks) ToggleDashboard();
            else if (command == MenuDirectory)
                TaskHistory.OpenDirectory(Path.Combine(_root, "Tasks"));
            else if (command == MenuExit)
                DestroyWindow(_ball);
        }
        finally
        {
            DestroyMenu(menu);
        }
    }

    private static void ReloadTasks()
    {
        var selectedId = SelectedTask()?.TaskId;
        _tasks = TaskHistory.Load(_root);
        if (selectedId is not null)
        {
            var index = _tasks.ToList().FindIndex(task => task.TaskId == selectedId);
            if (index >= 0) _selectedTask = index;
            else _outputPage = false;
        }
        _selectedTask = Math.Clamp(_selectedTask, 0, Math.Max(0, _tasks.Count - 1));
        _selectedOutput = Math.Clamp(_selectedOutput, 0,
            Math.Max(0, (SelectedTask()?.Outputs.Count ?? 0) - 1));
        _taskScroll = Math.Clamp(_taskScroll, 0, Math.Max(0, _tasks.Count - MaxVisibleRows));
        _outputScroll = Math.Clamp(_outputScroll, 0,
            Math.Max(0, (SelectedTask()?.Outputs.Count ?? 0) - 4));
    }

    private static LocalTaskItem? SelectedTask() =>
        _selectedTask < _tasks.Count ? _tasks[_selectedTask] : null;

    private static void OpenSelectedOutput(bool directory)
    {
        var outputs = SelectedTask()?.Outputs ?? Array.Empty<LocalTaskOutput>();
        if (_selectedOutput >= outputs.Count) return;
        var path = outputs[_selectedOutput].FullPath;
        if (directory) TaskHistory.OpenDirectory(path, selectFile: true);
        else TaskHistory.OpenFile(path);
    }

    private static void DrawLabel(
        IntPtr dc,
        string text,
        int x,
        int y,
        int width,
        int height,
        int size,
        int weight,
        uint color,
        bool center = false)
    {
        if (width <= 0 || height <= 0) return;
        using var font = new GdiObject(CreateUiFont(size, weight));
        var old = SelectObject(dc, font.Handle);
        SetTextColor(dc, color);
        var bounds = new Rect(x, y, x + width, y + height);
        DrawText(
            dc,
            text,
            -1,
            ref bounds,
            (center ? DtCenter : DtLeft) | DtVCenter | DtSingleLine | DtEndEllipsis);
        SelectObject(dc, old);
    }

    private static IntPtr CreateUiFont(int pixels, int weight) => CreateFont(
        -pixels,
        0,
        0,
        0,
        weight,
        0,
        0,
        0,
        1,
        0,
        0,
        5,
        0,
        "Microsoft YaHei UI");

    private static string StatusText(string status) => status switch
    {
        "running" => "运行中",
        "completed" => "已完成",
        "waiting" => "等待继续",
        "cancelled" => "已取消",
        "failed" => "失败",
        _ => "未知",
    };

    private static (string Label, uint Color) AttentionState()
    {
        if (_tasks.FirstOrDefault()?.Status == "waiting")
            return ("需要你完成操作", ColorRef(245, 158, 11));
        if (_tasks.FirstOrDefault()?.Status == "failed")
            return ("最近操作失败", ColorRef(220, 38, 38));
        if (_tasks.Any(task => task.Status == "running"))
            return ("任务正在执行", ColorRef(22, 163, 74));
        if (!_connected())
            return ("正在重新连接", ColorRef(107, 114, 128));
        return ("已连接，可以开始创作", ColorRef(37, 99, 235));
    }

    private static uint StatusColor(string status) => status switch
    {
        "running" => ColorRef(47, 100, 232),
        "completed" => ColorRef(25, 142, 72),
        "failed" => ColorRef(210, 55, 55),
        _ => ColorRef(112, 119, 130),
    };

    private static string FormatSize(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB"];
        double value = bytes;
        var unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }
        return $"{value:0.#} {units[unit]}";
    }

    private static bool Contains(Rect bounds, int x, int y) =>
        x >= bounds.Left && x < bounds.Right && y >= bounds.Top && y < bounds.Bottom;

    private static int LowWord(IntPtr value) => unchecked((short)((long)value & 0xffff));
    private static int HighWord(IntPtr value) => unchecked((short)(((long)value >> 16) & 0xffff));
    private static uint ColorRef(byte red, byte green, byte blue) =>
        (uint)(red | green << 8 | blue << 16);

    private sealed class GdiObject : IDisposable
    {
        internal IntPtr Handle { get; }
        private readonly bool _owns;

        internal GdiObject(IntPtr handle, bool owns = true)
        {
            Handle = handle;
            _owns = owns;
        }

        public void Dispose()
        {
            if (_owns && Handle != IntPtr.Zero) DeleteObject(Handle);
        }
    }

    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate IntPtr WndProc(IntPtr window, uint message, UIntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WindowClass
    {
        internal uint Size;
        internal uint Style;
        [MarshalAs(UnmanagedType.FunctionPtr)] internal WndProc WindowProcedure;
        internal int ClassExtra;
        internal int WindowExtra;
        internal IntPtr Instance;
        internal IntPtr Icon;
        internal IntPtr Cursor;
        internal IntPtr Background;
        internal string? MenuName;
        internal string ClassName;
        internal IntPtr SmallIcon;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Message
    {
        internal IntPtr Window;
        internal uint Value;
        internal UIntPtr WParam;
        internal IntPtr LParam;
        internal uint Time;
        internal Point Point;
        internal uint Private;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PaintStruct
    {
        internal IntPtr DeviceContext;
        [MarshalAs(UnmanagedType.Bool)] internal bool Erase;
        internal Rect Paint;
        [MarshalAs(UnmanagedType.Bool)] internal bool Restore;
        [MarshalAs(UnmanagedType.Bool)] internal bool Update;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] internal byte[] Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct GdiplusStartupInput
    {
        internal uint Version;
        internal IntPtr DebugEventCallback;
        [MarshalAs(UnmanagedType.Bool)] internal bool SuppressBackgroundThread;
        [MarshalAs(UnmanagedType.Bool)] internal bool SuppressExternalCodecs;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Point
    {
        internal int X;
        internal int Y;

        internal Point(int x, int y)
        {
            X = x;
            Y = y;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        internal int Left;
        internal int Top;
        internal int Right;
        internal int Bottom;
        internal int Width => Right - Left;
        internal int Height => Bottom - Top;

        internal Rect(int left, int top, int right, int bottom)
        {
            Left = left;
            Top = top;
            Right = right;
            Bottom = bottom;
        }
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandle(string? moduleName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern ushort RegisterClassEx(ref WindowClass windowClass);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateWindowEx(
        uint extendedStyle,
        string className,
        string windowName,
        uint style,
        int x,
        int y,
        int width,
        int height,
        IntPtr parent,
        IntPtr menu,
        IntPtr instance,
        IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern IntPtr DefWindowProc(IntPtr window, uint message, UIntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern int GetMessage(out Message message, IntPtr window, uint minimum, uint maximum);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TranslateMessage(ref Message message);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessage(ref Message message);

    [DllImport("user32.dll")]
    private static extern void PostQuitMessage(int exitCode);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ShowWindow(IntPtr window, int command);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateWindow(IntPtr window);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyWindow(IntPtr window);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr window);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(IntPtr window);

    [DllImport("user32.dll")]
    private static extern IntPtr LoadCursor(IntPtr instance, IntPtr cursorName);

    [DllImport("user32.dll")]
    private static extern IntPtr BeginPaint(IntPtr window, out PaintStruct paint);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EndPaint(IntPtr window, ref PaintStruct paint);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetClientRect(IntPtr window, out Rect bounds);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetWindowRect(IntPtr window, out Rect bounds);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InvalidateRect(IntPtr window, IntPtr bounds, bool erase);

    [DllImport("user32.dll")]
    private static extern UIntPtr SetTimer(IntPtr window, UIntPtr id, uint interval, IntPtr callback);

    [DllImport("user32.dll")]
    private static extern IntPtr SetCapture(IntPtr window);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetCursorPos(out Point point);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowPos(
        IntPtr window,
        IntPtr insertAfter,
        int x,
        int y,
        int width,
        int height,
        uint flags);

    [DllImport("user32.dll")]
    private static extern int SetWindowRgn(IntPtr window, IntPtr region, bool redraw);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SystemParametersInfo(int action, int parameter, out Rect bounds, int flags);

    [DllImport("user32.dll")]
    private static extern IntPtr CreatePopupMenu();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AppendMenu(IntPtr menu, uint flags, int identifier, string text);

    [DllImport("user32.dll")]
    private static extern int TrackPopupMenu(
        IntPtr menu,
        uint flags,
        int x,
        int y,
        int reserved,
        IntPtr owner,
        IntPtr bounds);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyMenu(IntPtr menu);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateSolidBrush(uint color);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateEllipticRgn(int left, int top, int right, int bottom);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRoundRectRgn(int left, int top, int right, int bottom, int width, int height);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreatePen(int style, int width, uint color);

    [DllImport("gdi32.dll")]
    private static extern IntPtr GetStockObject(int index);

    [DllImport("gdi32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool RoundRect(IntPtr dc, int left, int top, int right, int bottom, int ellipseWidth, int ellipseHeight);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr owner, string text, string caption, uint type);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdiplusStartup(out IntPtr token, ref GdiplusStartupInput input, IntPtr output);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern void GdiplusShutdown(IntPtr token);

    [DllImport("gdiplus.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern int GdipLoadImageFromFile(string filename, out IntPtr image);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipDisposeImage(IntPtr image);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipCreateFromHDC(IntPtr dc, out IntPtr graphics);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipDeleteGraphics(IntPtr graphics);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipCreatePath(int fillMode, out IntPtr path);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipDeletePath(IntPtr path);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipAddPathEllipseI(IntPtr path, int x, int y, int width, int height);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipSetClipPath(IntPtr graphics, IntPtr path, int combineMode);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipDrawImageRectI(IntPtr graphics, IntPtr image, int x, int y, int width, int height);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipSetInterpolationMode(IntPtr graphics, int mode);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipSetSmoothingMode(IntPtr graphics, int mode);

    [DllImport("gdiplus.dll", ExactSpelling = true)]
    private static extern int GdipSetPixelOffsetMode(IntPtr graphics, int mode);

    [DllImport("gdi32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DeleteObject(IntPtr value);

    [DllImport("user32.dll")]
    private static extern int FillRect(IntPtr deviceContext, ref Rect bounds, IntPtr brush);

    [DllImport("gdi32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Ellipse(IntPtr deviceContext, int left, int top, int right, int bottom);

    [DllImport("gdi32.dll")]
    private static extern int SetBkMode(IntPtr deviceContext, int mode);

    [DllImport("gdi32.dll")]
    private static extern uint SetTextColor(IntPtr deviceContext, uint color);

    [DllImport("gdi32.dll")]
    private static extern IntPtr SelectObject(IntPtr deviceContext, IntPtr value);

    [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateFont(
        int height,
        int width,
        int escapement,
        int orientation,
        int weight,
        uint italic,
        uint underline,
        uint strikeOut,
        uint characterSet,
        uint outputPrecision,
        uint clipPrecision,
        uint quality,
        uint pitchAndFamily,
        string faceName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int DrawText(
        IntPtr deviceContext,
        string text,
        int count,
        ref Rect bounds,
        uint format);
}
