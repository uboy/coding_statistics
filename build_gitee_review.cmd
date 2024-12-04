echo on
setlocal EnableDelayedExpansion

set compile_file_name=gitee_review
rem set upx_path="Z:\D_Share\Installs\Utils\upx-3.96-win64"
set upx_path=""


rem list of dependencies
set modules_list=jira pyinstaller openpyxl
rem check if dependencies installed
for %%a in (%modules_list%) do (
   echo %%a
   pip list | find "%%a"
   if errorlevel 1 (
    start /WAIT pip install %%a
    if errorlevel 1 (
      echo "%%a cannot be installed. Exiting"
      pause
      exit /B 1
    )
   )
)

pyinstaller --onefile --console --clean --upx-dir %upx_path%  "%compile_file_name%.py"

move /y dist\%compile_file_name%.exe %compile_file_name%.exe

pause