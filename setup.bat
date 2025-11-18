@echo off
echo =========================================
echo   Clothing Rental System Setup
echo =========================================
echo.

REM Check Python installation
echo Checking Python version...
python --version
if errorlevel 1 (
    echo Error: Python is not installed. Please install Python 3.8 or higher.
    pause
    exit /b 1
)

REM Create virtual environment
echo.
echo Creating virtual environment...
python -m venv venv

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo.
echo Installing dependencies...
pip install Flask==3.0.0 Flask-SQLAlchemy==3.1.1 Flask-Login==0.6.3 Werkzeug==3.0.1 reportlab==4.0.7

REM Create directories
echo.
echo Creating directories...
if not exist templates mkdir templates
if not exist static\uploads mkdir static\uploads

REM Check files
echo.
echo Checking required files...
if not exist app.py (
    echo WARNING: app.py not found!
    echo Please copy app.py to this folder.
)

if not exist templates\base.html (
    echo WARNING: Template files not found!
    echo Please copy all HTML files to templates\ folder.
)

REM Summary
echo.
echo =========================================
echo   Setup Complete!
echo =========================================
echo.
echo Next steps:
echo 1. Make sure app.py is in this folder
echo 2. Make sure all HTML templates are in templates\ folder
echo 3. Run: python app.py
echo 4. Open browser: http://localhost:5000
echo 5. Login: admin@rental.com / admin123
echo.
echo Happy renting! 🎉
echo =========================================
echo.
pause