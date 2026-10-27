"""Тест обезличивания страниц объявлений перед добавлением в фикстуры."""

from scripts.anonymize_listing import anonymize
from tests.helpers import fixture_text


def test_removes_seller_name_phone_and_scripts() -> None:
    html = fixture_text("avito", "item_gpu_rtx3060.html").replace(
        "</body>", "<script>track()</script><p>Звоните +7 (912) 345-67-89</p></body>"
    )
    result = anonymize(html)
    assert "Игорь" not in result
    assert "345-67-89" not in result
    assert "<script" not in result
    assert "Продавец" in result
    assert "RTX 3060" in result


def test_seller_profile_links_are_removed() -> None:
    """22.2: ссылки на профиль и магазин продавца (по ним его можно найти) вычищаются."""
    from scripts.anonymize_listing import anonymize

    html = (
        '<a href="https://www.avito.ru/user/c1a6643204275d0fd0f58b373ee34b49/profile?id=1">x</a>'
        '<a href="/brands/i8228896?shopId=8030781">y</a>'
        '<a href="https://www.avito.ru/brands/c900207d0cea943a2fbeb7c0e2c47d78?shopId=3">z</a>'
        '<a href="https://www.avito.ru/moskva/tovary_dlya_kompyutera/item_1">товар</a>'
    )
    result = anonymize(html)
    for secret in ("c1a6643204275d0fd0f58b373ee34b49", "i8228896", "8030781", "c900207d0cea"):
        assert secret not in result
    assert "tovary_dlya_kompyutera/item_1" in result  # ссылки на товары остаются
