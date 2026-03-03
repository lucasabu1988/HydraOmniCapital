Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\caslu\Desktop\NuevoProyecto"
WshShell.Run """C:\Users\caslu\AppData\Local\Python\pythoncore-3.14-64\python.exe"" ""C:\Users\caslu\Desktop\NuevoProyecto\compass_watchdog.py""", 0, False
