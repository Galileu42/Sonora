#include <windows.h>
#include <stdio.h>
#include <wchar.h>

static wchar_t temp[MAX_PATH], folder[MAX_PATH], script[MAX_PATH], archive[MAX_PATH];
static wchar_t system_dir[MAX_PATH], shell[MAX_PATH], command[4 * MAX_PATH];

static BOOL save_resource(HINSTANCE instance, WORD id, const wchar_t *path) {
    HRSRC resource = FindResourceW(instance, MAKEINTRESOURCEW(id), RT_RCDATA);
    if (!resource) return FALSE;
    HGLOBAL data = LoadResource(instance, resource);
    if (!data) return FALSE;
    DWORD size = SizeofResource(instance, resource), written = 0;
    HANDLE output = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE) return FALSE;
    BOOL ok = WriteFile(output, LockResource(data), size, &written, NULL) && written == size;
    CloseHandle(output);
    return ok;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show) {
    (void)previous; (void)args; (void)show;
    DWORD result = 1;
    DWORD length = GetTempPathW(ARRAYSIZE(temp), temp);
    if (!length || length >= ARRAYSIZE(temp) - 16 || !GetTempFileNameW(temp, L"SNR", 0, folder))
        goto error;
    if (!DeleteFileW(folder) || !CreateDirectoryW(folder, NULL))
        goto error;
    if (swprintf(script, ARRAYSIZE(script), L"%ls\\install.ps1", folder) < 0 ||
        swprintf(archive, ARRAYSIZE(archive), L"%ls\\Sonora_Windows.zip", folder) < 0 ||
        !save_resource(instance, 201, script) || !save_resource(instance, 202, archive))
        goto cleanup;
    if (!GetSystemDirectoryW(system_dir, ARRAYSIZE(system_dir)) ||
        swprintf(shell, ARRAYSIZE(shell), L"%ls\\WindowsPowerShell\\v1.0\\powershell.exe", system_dir) < 0 ||
        swprintf(command, ARRAYSIZE(command),
            L"\"%ls\" -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"%ls\"", shell, script) < 0)
        goto cleanup;
    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {0};
    if (CreateProcessW(shell, command, NULL, NULL, FALSE, CREATE_NEW_CONSOLE, NULL, folder, &startup, &process)) {
        WaitForSingleObject(process.hProcess, INFINITE);
        GetExitCodeProcess(process.hProcess, &result);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }
cleanup:
    DeleteFileW(script);
    DeleteFileW(archive);
    RemoveDirectoryW(folder);
    if (result == 0 || result == 2) return result;
error:
    MessageBoxW(NULL, L"Não foi possível concluir a instalação do Sonora.", L"Sonora", MB_OK | MB_ICONERROR);
    return 1;
}
