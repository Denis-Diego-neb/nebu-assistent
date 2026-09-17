#include "NebulaAuth.h"

#include <dpapi.h>
#include <shlwapi.h>
#include <strsafe.h>
#include <vector>

namespace
{
HRESULT ProgramDataPath(PCWSTR name, PWSTR path, size_t count)
{
    wchar_t root[MAX_PATH] = {};
    DWORD length = GetEnvironmentVariableW(L"ProgramData", root, ARRAYSIZE(root));
    if (!length || length >= ARRAYSIZE(root))
    {
        StringCchCopyW(root, ARRAYSIZE(root), L"C:\\ProgramData");
    }
    return StringCchPrintfW(path, count, L"%s\\Nebula\\%s", root, name);
}

bool ReadFileBytes(PCWSTR name, std::vector<BYTE> &bytes)
{
    wchar_t path[MAX_PATH] = {};
    if (FAILED(ProgramDataPath(name, path, ARRAYSIZE(path)))) return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER size = {};
    bool ok = GetFileSizeEx(file, &size) && size.QuadPart > 0 && size.QuadPart <= 65536;
    if (ok)
    {
        bytes.resize(static_cast<size_t>(size.QuadPart));
        DWORD read = 0;
        ok = ReadFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &read, nullptr) &&
             read == bytes.size();
    }
    CloseHandle(file);
    return ok;
}

long long UnixTimeNow()
{
    FILETIME fileTime = {};
    GetSystemTimeAsFileTime(&fileTime);
    ULARGE_INTEGER value = {};
    value.LowPart = fileTime.dwLowDateTime;
    value.HighPart = fileTime.dwHighDateTime;
    return static_cast<long long>(value.QuadPart / 10000000ULL - 11644473600ULL);
}
}

bool NebulaCredentialConfigured()
{
    wchar_t path[MAX_PATH] = {};
    return SUCCEEDED(ProgramDataPath(L"windows_password.bin", path, ARRAYSIZE(path))) &&
           PathFileExistsW(path);
}

bool NebulaUnlockAuthorized()
{
    std::vector<BYTE> bytes;
    if (!ReadFileBytes(L"unlock.authorized", bytes)) return false;
    bytes.push_back(0);
    const long long expires = _strtoi64(reinterpret_cast<const char *>(bytes.data()), nullptr, 10);
    if (expires < UnixTimeNow() || expires > UnixTimeNow() + 180)
    {
        wchar_t path[MAX_PATH] = {};
        if (SUCCEEDED(ProgramDataPath(L"unlock.authorized", path, ARRAYSIZE(path))))
        {
            DeleteFileW(path);
        }
        return false;
    }
    return true;
}

bool ConsumeNebulaUnlockAuthorization()
{
    if (!NebulaUnlockAuthorized()) return false;
    wchar_t path[MAX_PATH] = {};
    return SUCCEEDED(ProgramDataPath(L"unlock.authorized", path, ARRAYSIZE(path))) &&
           DeleteFileW(path);
}

HRESULT LoadNebulaProtectedPassword(PWSTR *password)
{
    if (!password) return E_INVALIDARG;
    *password = nullptr;
    std::vector<BYTE> encrypted;
    if (!ReadFileBytes(L"windows_password.bin", encrypted))
    {
        return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    }
    DATA_BLOB input = {static_cast<DWORD>(encrypted.size()), encrypted.data()};
    DATA_BLOB output = {};
    if (!CryptUnprotectData(&input, nullptr, nullptr, nullptr, nullptr,
                            CRYPTPROTECT_UI_FORBIDDEN, &output))
    {
        return HRESULT_FROM_WIN32(GetLastError());
    }
    const size_t characters = output.cbData / sizeof(wchar_t);
    PWSTR result = static_cast<PWSTR>(CoTaskMemAlloc((characters + 1) * sizeof(wchar_t)));
    if (!result)
    {
        SecureZeroMemory(output.pbData, output.cbData);
        LocalFree(output.pbData);
        return E_OUTOFMEMORY;
    }
    CopyMemory(result, output.pbData, output.cbData);
    result[characters] = L'\0';
    SecureZeroMemory(output.pbData, output.cbData);
    LocalFree(output.pbData);
    *password = result;
    return S_OK;
}

HRESULT LoadNebulaTargetSid(PWSTR *sid)
{
    if (!sid) return E_INVALIDARG;
    *sid = nullptr;
    std::vector<BYTE> bytes;
    if (!ReadFileBytes(L"target_sid.txt", bytes))
    {
        return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    }
    bytes.push_back(0);
    const char *source = reinterpret_cast<const char *>(bytes.data());
    const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, source, -1,
                                          nullptr, 0);
    if (count <= 0) return HRESULT_FROM_WIN32(GetLastError());
    PWSTR result = static_cast<PWSTR>(CoTaskMemAlloc(count * sizeof(wchar_t)));
    if (!result) return E_OUTOFMEMORY;
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, source, -1, result, count))
    {
        const HRESULT error = HRESULT_FROM_WIN32(GetLastError());
        CoTaskMemFree(result);
        return error;
    }
    *sid = result;
    return S_OK;
}
