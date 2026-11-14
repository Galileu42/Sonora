#define _UNICODE
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <wchar.h>

static wchar_t root[32768], python_home[32768], dll[32768], python[32768], script[32768];

static int fail(const wchar_t *message) {
    MessageBoxW(NULL, message, L"Sonora", MB_ICONERROR | MB_OK);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    (void)instance; (void)previous; (void)command_line; (void)show;
    DWORD length = GetModuleFileNameW(NULL, root, ARRAYSIZE(root));
    if (!length || length >= ARRAYSIZE(root) - 64)
        return fail(L"Não foi possível localizar a pasta do Sonora.");
    wchar_t *separator = wcsrchr(root, L'\\');
    if (!separator) return fail(L"Não foi possível localizar a pasta do Sonora.");
    *separator = L'\0';

    swprintf(python, ARRAYSIZE(python), L"%ls\\.venv\\Scripts\\pythonw.exe", root);
    swprintf(script, ARRAYSIZE(script), L"%ls\\sonora.py", root);
    swprintf(dll, ARRAYSIZE(dll), L"%ls\\.venv\\pyvenv.cfg", root);
    FILE *config = _wfopen(dll, L"rb");
    if (!config) return fail(L"Abra Abrir_Sonora.cmd para preparar o aplicativo.");
    char line[32768];
    unsigned major = 0, minor = 0;
    while (fgets(line, sizeof line, config)) {
        if (strncmp(line, "home = ", 7) == 0) {
            line[strcspn(line, "\r\n")] = 0;
            MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, line + 7, -1, python_home, ARRAYSIZE(python_home));
        }
        if (strncmp(line, "version = ", 10) == 0)
            sscanf(line + 10, "%u.%u", &major, &minor);
    }
    fclose(config);
    if (!python_home[0] || major != 3 || minor < 10)
        return fail(L"O ambiente Python do Sonora está incompleto. Execute Preparar.cmd.");
    if (swprintf(dll, ARRAYSIZE(dll), L"%ls\\python%u%u.dll", python_home, major, minor) < 0)
        return fail(L"O caminho da instalação do Python é longo demais.");
    HMODULE runtime = LoadLibraryExW(dll, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!runtime) return fail(L"O Python usado pelo Sonora foi movido ou está incompleto. Execute Preparar.cmd.");
    int (*python_main)(int, wchar_t **) = (void *)GetProcAddress(runtime, "Py_Main");
    if (!python_main) return fail(L"O Python instalado não é compatível com o Sonora.");
    // Match CPython's venv redirector so sys.executable and site-packages
    // resolve to the prepared environment, while this EXE owns the window.
    SetEnvironmentVariableW(L"__PYVENV_LAUNCHER__", python);
    wchar_t *arguments[] = {python, script, NULL};
    int result = python_main(2, arguments);
    if (result != 0)
        return fail(L"O Sonora não conseguiu iniciar. Abra Abrir_Sonora.cmd para verificar a instalação.");
    return 0;
}
