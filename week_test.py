import pandas as pd
from datetime import datetime, timedelta

def get_valid_weeks(start_date_str, end_date_str):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    start_monday = start_date - timedelta(days=start_date.weekday())
    weeks = pd.date_range(start=start_monday, end=end_date, freq='W-MON')
    return weeks.strftime("%G-W%V").tolist()

def test_week_coverage(start_date, end_date):
    weeks = get_valid_weeks(str(start_date), str(end_date))

    missing_dates = []
    for day in range((end_date - start_date).days + 1):
        current = start_date + timedelta(days=day)
        iso_year, iso_week, _ = current.isocalendar()
        iso_code = f"{iso_year}-W{iso_week:02d}"
        if iso_code not in weeks:
            missing_dates.append(str(current))

    test_name = f"Тест от {start_date} до {end_date}"
    if missing_dates:
        print(f"❌ {test_name}: пропущены даты: {missing_dates}")
    else:
        print(f"✅ {test_name}: все даты покрыты ({len(weeks)} недель)")

# Базовая дата: понедельник 2025-03-31
base_start = datetime.strptime("2025-03-31", "%Y-%m-%d").date()

# Генерация тестов: все варианты начала и конца недели (по 7)
for start_offset in range(7):
    for end_offset in range(7):
        start = base_start + timedelta(days=start_offset)
        end = base_start + timedelta(days=30 + end_offset)  # в следующем месяце
        test_week_coverage(start, end)
