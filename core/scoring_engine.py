import re


def _is_large_company(biz: dict) -> bool:
    _, review_count = _parse_rating_and_reviews(biz.get("rating", ""))
    name = (biz.get("name", "") or "").lower()
    category = (biz.get("category", "") or "").lower()

    large_keywords = ["grupo", "s/a", "s.a", "matriz", "indústria e comércio"]

    if review_count >= 200:
        return True
    for kw in large_keywords:
        if kw in name:
            return True

    return False


def _estimate_business_size(biz: dict) -> str:
    _, review_count = _parse_rating_and_reviews(biz.get("rating", ""))
    name = (biz.get("name", "") or "")

    if _is_large_company(biz):
        return "grande"

    if review_count <= 10:
        return "pequena"
    if review_count <= 50:
        return "media"

    return "pequena"


def calculate_purchase_potential(biz: dict) -> int:
    has_website = biz.get("has_website", False)
    site_check = biz.get("site_check", {}) or {}
    quality = site_check.get("quality", "none")

    rating_value, review_count = _parse_rating_and_reviews(biz.get("rating", ""))

    small_biz_bonus = _small_business_bonus(review_count)

    whatsapp_bonus = 12 if site_check.get("has_whatsapp", False) else 0

    if _is_large_company(biz):
        large_penalty = -50
    else:
        large_penalty = 0

    if not has_website or quality == "none":
        score = 90 + small_biz_bonus + whatsapp_bonus + large_penalty
        return max(0, min(score, 100))

    if quality == "ruim":
        base = 70
        if site_check.get("load_time_ms", 0) > 5000:
            base += 5
        if not site_check.get("has_viewport", False):
            base += 5
        score = base + small_biz_bonus + whatsapp_bonus + large_penalty
        return max(0, min(score, 90))

    if quality == "medio":
        base = 50
        score = base + small_biz_bonus + whatsapp_bonus + large_penalty
        return max(0, min(score, 75))

    if quality == "bom":
        base = 20 + whatsapp_bonus
        score = base + small_biz_bonus + large_penalty
        return max(0, min(score, 45))

    return max(0, 50 + large_penalty)


def _parse_rating_and_reviews(rating_str: str) -> tuple:
    if not rating_str:
        return (0.0, 0)

    rating = 0.0
    reviews = 0

    match = re.search(r'(\d+)[,.](\d+)', rating_str)
    if match:
        rating = float(f"{match.group(1)}.{match.group(2)}")

    match = re.search(r'(\d+)\s*comentários', rating_str)
    if match:
        reviews = int(match.group(1))
    else:
        match = re.search(r'\((\d+)\)', rating_str)
        if match:
            reviews = int(match.group(1))

    return (rating, reviews)


def recalculate_all_scores(prospects_path: str = None):
    """Recalcula o purchase_potential de TODAS as empresas no JSON,
    sobrescrevendo os scores antigos com os novos scores determinísticos.
    Útil para migrar dados existentes para o novo sistema de scoring.
    """
    import json
    from pathlib import Path

    if prospects_path is None:
        prospects_path = Path(__file__).resolve().parent.parent / "memory" / "business_prospects.json"

    path = Path(prospects_path)
    if not path.exists():
        print(f"[Scoring Engine] Arquivo não encontrado: {path}")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        businesses = json.load(f)

    updated = 0
    for biz in businesses:
        if "analysis" not in biz:
            biz["analysis"] = {}
        old_score = biz["analysis"].get("purchase_potential", None)
        new_score = calculate_purchase_potential(biz)
        biz["analysis"]["purchase_potential"] = new_score
        updated += 1
        if old_score is not None and old_score != new_score:
            name = biz.get("name", "Desconhecida")
            print(f"[Scoring Engine] {name}: {old_score} -> {new_score}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(businesses, f, indent=4, ensure_ascii=False)

    print(f"[Scoring Engine] Scores recalculados para {updated} empresas.")
    return updated


def _small_business_bonus(review_count: int) -> int:
    if review_count <= 2:
        return 8
    if review_count <= 5:
        return 5
    if review_count <= 15:
        return 3
    if review_count <= 30:
        return 1
    return 0


if __name__ == "__main__":
    recalculate_all_scores()
