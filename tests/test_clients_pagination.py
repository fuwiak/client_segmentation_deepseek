from app.main import _pagination_pages


def test_pagination_pages_single_page() -> None:
    assert _pagination_pages(1, 1) == [1]


def test_pagination_pages_with_ellipsis() -> None:
    assert _pagination_pages(5, 10) == [1, None, 3, 4, 5, 6, 7, None, 10]


def test_pagination_pages_near_start() -> None:
    assert _pagination_pages(2, 8) == [1, 2, 3, 4, None, 8]
