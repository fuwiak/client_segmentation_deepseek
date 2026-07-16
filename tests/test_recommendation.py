from app.services.segmentation import SegmentationService


def test_heuristic_recommendation_for_birthday_tag() -> None:
    row = {
        "Теги": "#деньрождения",
        "Саммари": "События: день рождения — месяц не найден в данных.",
        "Телефон": "+79001234567",
        "Всего заказов": 3,
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "Свяжитесь" in rec
    assert "Касание:" not in rec
    assert "уточнить" in rec.lower()
    assert "за 3 дня" not in rec.lower() or "без даты" in rec.lower() or "уточнить" in rec.lower()


def test_heuristic_recommendation_for_birthday_with_month() -> None:
    row = {
        "Теги": "#деньрождения",
        "Дата рождения": "12.07.1990",
        "Телефон": "+79001234567",
        "ТГ ник": "@viktor",
        "Всего заказов": 5,
        "Средний чек": 5700,
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "Свяжитесь" in rec
    assert "Касание:" not in rec
    assert "Оффер:" not in rec
    assert "июл" in rec.lower()
    assert "12" in rec
    assert "Telegram" in rec
    assert "чек" in rec.lower()
    # без дубля суммы
    assert rec.count("5700") <= 1 or "примерно на 5700" in rec


def test_heuristic_recommendation_for_march_event_segment() -> None:
    row = {
        "Группы": "флаувау / событие марта",
        "Телефон": "+79001234567",
        "Всего заказов": 10,
        "_orders_context": [
            {"Дата": "09.03.2026", "Комментарий": "Flowwow", "Сумма": 5000},
        ],
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "март" in rec.lower()
    assert "предложите" in rec.lower()
    assert "Касание:" not in rec


def test_order_marketing_patterns_from_history() -> None:
    row = {
        "Телефон": "+79001234567",
        "_orders_context": [
            {"Дата": "26.05.2026", "Сумма": 10000, "Канал продаж": "Telegram", "Позиции": "Пион"},
            {"Дата": "15.05.2026", "Сумма": 9000, "Канал продаж": "Telegram", "Позиции": "Пион"},
            {"Дата": "25.03.2026", "Сумма": 15000, "Канал продаж": "Прямые продажи"},
            {"Дата": "22.12.2025", "Сумма": 76000, "Позиции": "Амариллис воск. Veresk"},
            {"Дата": "07.03.2025", "Сумма": 16000, "Канал продаж": "Витрина"},
            {"Дата": "27.12.2024", "Сумма": 50000, "Позиции": "Композиция новогодняя"},
            {"Дата": "08.12.2024", "Сумма": 44920, "Позиции": "Новогодняя композиция"},
            {
                "Дата": "28.11.2024",
                "Сумма": 15000,
                "Комментарий": "Нежный букет в подарок невесте бюджет 15",
            },
        ],
    }
    patterns = SegmentationService.build_order_marketing_patterns(row)
    occasions = " ".join(str(p.get("occasion") or "") for p in patterns)
    assert "Новый год" in occasions or "декабр" in occasions.lower()
    assert "8 марта" in occasions or "март" in occasions.lower()
    assert any(p.get("recurrent_yearly") for p in patterns)

    summary = SegmentationService._heuristic_intent_summary(row)
    assert summary is not None
    assert "касание" in summary.lower() or "сезонность" in summary.lower() or "окна" in summary.lower()
    assert "декабр" in summary.lower() or "Новый год" in summary
    assert "Маркетинг:" not in summary
    assert "Intent:" not in summary
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "Свяжитесь" in rec
    assert "декабр" in rec.lower() or "ноябр" in rec.lower() or "Новый год" in rec


def test_heuristic_recommendation_for_new_client_without_orders() -> None:
    row = {
        "Наименование": "Аренда",
        "Тип контрагента": "Юридическое лицо",
        "Телефон": "+79001234567",
        "Всего заказов": 0,
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "Свяжитесь" in rec
    assert "WhatsApp" in rec
    assert "привычном среднем чеке" not in rec
    assert "8 марта" in rec or "14 февраля" in rec or "праздник" in rec.lower() or "сентябр" in rec.lower()


def test_first_order_before_womens_day() -> None:
    row = {
        "Телефон": "+79001234567",
        "Всего заказов": 1,
        "_orders_context": [
            {"Дата": "05.03.2026", "Сумма": 4500, "Позиции": "Тюльпан"},
        ],
    }
    holiday = SegmentationService._holiday_for_order_date(2026, 3, 5)
    assert holiday is not None
    assert "8 марта" in holiday["occasion"]

    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "8 марта" in rec
    assert "Первый заказ" in rec or "похож" in rec.lower()
    assert "Касание:" not in rec
    assert "привычном среднем чеке" not in rec
    assert "ниже среднего" in rec or "выше среднего" in rec or "около среднего" in rec


def test_first_order_before_valentines() -> None:
    row = {
        "Телефон": "+79001234567",
        "Всего заказов": 1,
        "_orders_count": 1,
        "_orders_context": [
            {"Дата": "12.02.2026", "Сумма": 6000, "Комментарий": "доставка к 18:00"},
        ],
    }
    holiday = SegmentationService._holiday_for_order_date(2026, 2, 12)
    assert holiday is not None
    assert "14 февраля" in holiday["occasion"]

    rec = SegmentationService._heuristic_recommendation(row)
    assert "14 февраля" in rec
    assert "Первый заказ" in rec or "похож" in rec.lower()
    assert "предложите" in rec.lower()
    assert "Оффер:" not in rec


def test_empty_avg_check_march_segment_no_generic_avg_phrase() -> None:
    row = {
        "Телефон": "+79587570138",
        "Группы": "корпоративный клиент / событие марта",
        "Всего заказов": 0,
        "Средний чек": None,
        "Заказчик или получатель": "+79587570138 доб. 06793",
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "привычном среднем чеке" not in rec
    assert "8 марта" in rec or "март" in rec.lower()
    assert "тюльпан" in rec.lower() or "весенний" in rec.lower() or "предложите" in rec.lower()


def test_no_duplicate_budget_in_recommendation() -> None:
    row = {
        "Телефон": "+79001234567",
        "ВИП": "да",
        "Средний чек": 6116,
        "Всего заказов": 5,
        "_orders_context": [
            {"Дата": "21.05.2026", "Сумма": 23000, "Комментарий": "подарок"},
        ],
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert rec is not None
    assert "Касание:" not in rec
    assert "~6116 р. ~6116" not in rec
    assert rec.count("6116") <= 2  # чек в оффере и в сравнении — ок, но не дубль подряд
    assert "VIP:" not in rec
    assert "WhatsApp" in rec


def test_peer_benchmarks_and_similar_first_order() -> None:
    peers_rows = [
        {
            "Канал продаж": "Flowwow",
            "Средний чек": 8000,
            "_orders_context": [{"Дата": "04.03.2026", "Сумма": 8200}],
        },
        {
            "Канал продаж": "Flowwow",
            "Средний чек": 7000,
            "_orders_context": [{"Дата": "06.03.2026", "Сумма": 7100}],
        },
        {
            "Канал продаж": "Витрина",
            "Средний чек": 4000,
            "_orders_context": [{"Дата": "10.01.2026", "Сумма": 4000}],
        },
    ]
    peers = SegmentationService.build_peer_benchmarks(peers_rows)
    assert peers["store_median_check"] > 0
    assert "Flowwow" in peers["by_channel"]

    row = {
        "Телефон": "+79001112233",
        "Канал продаж": "Flowwow",
        "Всего заказов": 1,
        "_orders_count": 1,
        "_orders_context": [{"Дата": "05.03.2026", "Сумма": 4500, "Позиции": "Тюльпан"}],
        "_peer_benchmarks": peers,
    }
    rec = SegmentationService._heuristic_recommendation(row)
    assert "Свяжитесь" in rec
    assert "8 марта" in rec
    assert "похож" in rec.lower()
    assert "Касание:" not in rec
    assert "ниже среднего" in rec or "выше среднего" in rec or "около среднего" in rec
