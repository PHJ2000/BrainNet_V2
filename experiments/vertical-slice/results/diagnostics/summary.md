# Diagnostic contract results

| Implementation | Case | Status | Code | Response contract | Log trace | Rollback |
|---|---|---:|---|---|---|---|
| fastapi-legacy | validation | 422 | VALIDATION_ERROR | True | True | - |
| fastapi-legacy | missing | 404 | NODE_NOT_FOUND | True | True | - |
| fastapi-legacy | conflict | 200 | None | False | True | - |
| fastapi-legacy | db | 500 | DB_ERROR | True | True | True |
| fastapi-safe | validation | 422 | VALIDATION_ERROR | True | True | - |
| fastapi-safe | missing | 404 | NODE_NOT_FOUND | True | True | - |
| fastapi-safe | conflict | 409 | VERSION_CONFLICT | True | True | - |
| fastapi-safe | db | 500 | DB_ERROR | True | True | True |
| spring | validation | 422 | VALIDATION_ERROR | True | True | - |
| spring | missing | 404 | NODE_NOT_FOUND | True | True | - |
| spring | conflict | 409 | VERSION_CONFLICT | True | True | - |
| spring | db | 500 | DB_ERROR | True | True | True |
