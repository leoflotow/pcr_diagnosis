Option Explicit
Dim shell, fs, root, python, launcher
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(fs.GetParentFolderName(WScript.ScriptFullName))
python = fs.BuildPath(root, ".venv\Scripts\pythonw.exe")
If Not fs.FileExists(python) Then
    MsgBox "Python environment not found. Please install the Windows edition or set up .venv first.", 48, "BioLabReview"
    WScript.Quit 1
End If
launcher = fs.BuildPath(root, "streamlit_launcher.py")
shell.CurrentDirectory = root
shell.Run """" & python & """ """ & launcher & """", 0, False
