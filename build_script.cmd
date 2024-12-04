echo on
setlocal EnableDelayedExpansion

set compile_file_name=%1
rem set upx_path="Z:\D_Share\Installs\Utils\upx-3.96-win64"
set upx_path=""


pip install -r requirements.txt

pyinstaller --onefile --console --clean --upx-dir %upx_path%  "%compile_file_name%.py"

move /y dist\%compile_file_name%.exe %compile_file_name%.exe

pause