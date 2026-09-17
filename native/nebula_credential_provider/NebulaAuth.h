#pragma once

#include <windows.h>

bool NebulaCredentialConfigured();
bool NebulaUnlockAuthorized();
bool ConsumeNebulaUnlockAuthorization();
HRESULT LoadNebulaProtectedPassword(_Outptr_result_nullonfailure_ PWSTR *password);
HRESULT LoadNebulaTargetSid(_Outptr_result_nullonfailure_ PWSTR *sid);
