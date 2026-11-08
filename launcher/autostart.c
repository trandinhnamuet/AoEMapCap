/* AoE-MapCap-start.exe: trình khởi chạy lúc đăng nhập Windows (tác vụ Task Scheduler "AoE-MapCap", mapcap/winstartup.py).

   Tác vụ chạy chương trình này, chương trình này chạy:  "<AoE-MapCap.exe>" --tray --autostart  (nhận nguyên dòng tham số)
   với biến môi trường PYINSTALLER_SUPPRESS_SPLASH_SCREEN=1, để bộ nạp của exe một file (PyInstaller) không hiện màn
   hình chờ: mở máy thì app chạy ngầm ở khay, không nháy gì trên màn hình (người dùng 09/11). Tác vụ không đặt được biến
   môi trường, và mọi cách khác (cmd, powershell) đều chớp cửa sổ console; chương trình này là ứng dụng GUI không cửa sổ.

   Chạy với quyền của tác vụ (cao nhất) nên AoE-MapCap.exe (đòi quyền admin) chạy luôn, không hỏi UAC. Thoát ngay sau
   khi tạo tiến trình. Biên dịch: build.py (MSVC nếu có, không thì zig cc). */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR args, int show)
{
    (void)inst; (void)prev; (void)show;
    if (!args || !*args)
        return 2;
    SetEnvironmentVariableW(L"PYINSTALLER_SUPPRESS_SPLASH_SCREEN", L"1");
    size_t n = lstrlenW(args) + 1;
    PWSTR cmd = (PWSTR)HeapAlloc(GetProcessHeap(), 0, n * sizeof(WCHAR));   /* CreateProcessW cần bộ đệm ghi được */
    if (!cmd)
        return 3;
    lstrcpyW(cmd, args);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    ZeroMemory(&pi, sizeof pi);
    si.cb = sizeof si;
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
        return 1;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
