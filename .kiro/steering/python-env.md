# Python Environment Rule

## ALWAYS use the project-local venv

The **only** Python interpreter for this project is:

```
C:\Users\Yash\Desktop\Ultimate_Chatbot\Yash\Scripts\python.exe
C:\Users\Yash\Desktop\Ultimate_Chatbot\Yash\Scripts\pip.exe
```

## NEVER use any other environment

Do NOT use, reference, or run commands against:
- `base` conda env (`C:\Users\Yash\anaconda3`)
- `Yash` conda env (`C:\Users\Yash\.conda\envs\Yash`)
- `chatbot` conda env (`C:\Users\Yash\.conda\envs\chatbot`)
- `primeenv` conda env (`C:\Users\Yash\.conda\envs\primeenv`)
- Any global `pip` or `python` command that resolves outside the project venv

## Correct command patterns

Installing a package:
```powershell
& "C:\Users\Yash\Desktop\Ultimate_Chatbot\Yash\Scripts\pip.exe" install <package>
```

Running Python:
```powershell
& "C:\Users\Yash\Desktop\Ultimate_Chatbot\Yash\Scripts\python.exe" <script>
```

Installing from requirements.txt:
```powershell
& "C:\Users\Yash\Desktop\Ultimate_Chatbot\Yash\Scripts\pip.exe" install -r requirements.txt
```

## Why

The app is started via `start_servers.bat` which hardcodes:
```
set "PYTHON=%ROOT%Yash\Scripts\python.exe"
```

Anything installed outside this venv will NOT be available to the running app.
