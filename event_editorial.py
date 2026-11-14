"""Present official event details without a paid generation service."""
import re


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def clean_source_text(value):
    """Cut recommendations, pagination and municipal footer, even on short pages."""
    value = clean(value)
    value = re.split(
        r"ces [ée]v[ée]nements pourraient vous int[ée]resser|"
        r"abonnement aux informations|recevez les derni[èe]res actualit[ée]s|"
        r"mentions l[ée]gales|politique de confidentialit[ée]",
        value, maxsplit=1, flags=re.I,
    )[0]
    # Pagination following the last event in a listing (including a truncated cache).
    value = re.sub(r"\s+(?:\d+\s+){2,}(?:[.…]+\s*)?(?:\d+\s*)*(?:->|→)?\s*$", "", value)
    return value.strip()


def event_description(event, detail_text, practical):
    text = clean_source_text(detail_text)
    # The municipal detail page has a Retour link immediately before its content.
    if re.search(r"(?:^|\s)Retour\s", text):
        text = re.split(r"(?:^|\s)Retour\s+", text, maxsplit=1)[1]
    elif event.get("title") and text.startswith(event["title"]):
        # Without an identified content boundary, prefer the known list summary.
        text = ""
    for key in ("date_time", "location_name", "address", "email", "phone", "website"):
        marker = clean(practical.get(key, ""))
        if marker:
            position = text.casefold().find(marker.casefold())
            if position >= 0:
                text = text[:position]
    text = re.sub(r"\bDescription\s+", "", text).strip()
    return text or clean_source_text(event.get("summary", ""))


def practical_text(practical, when):
    place = ", ".join(filter(None, [
        clean(practical.get("location_name", "")).rstrip(" ,"),
        clean(practical.get("address", "")),
    ]))
    text = clean(practical.get("date_time", "")) or when
    if place:
        text += f", {place}"
    text = text.rstrip(" .") + "."
    contacts = []
    phone = clean(practical.get("phone", ""))
    if re.fullmatch(r"0\d{9}", phone):
        phone = " ".join(phone[i:i + 2] for i in range(0, 10, 2))
    if phone:
        contacts.append(phone)
    if practical.get("email"):
        contacts.append(clean(practical["email"]))
    if contacts:
        text += " Renseignements : " + " ou ".join(contacts) + "."
    return text


def local_editorial(event, detail_text, practical, when):
    title = clean(event["title"])
    summary = clean_source_text(event.get("summary", ""))
    description = event_description(event, detail_text, practical)
    subject = title.casefold()
    period = when if when.startswith("du ") else f"le {when}"
    if "culinaire" in subject or "cuisine" in subject:
        intro = f"À Nyons, l’{title[0].lower() + title[1:]} est proposé {period}."
        why = "L’intérêt de cet atelier est de préparer soi-même les accompagnements, au lieu de se limiter à choisir le plat principal. Regardez les recettes au programme pour choisir ce que vous aimeriez apprendre à refaire chez vous."
        question = "Quel accompagnement aimeriez-vous préparer vous-même pour les fêtes ?" if "fête" in subject else "Quelle préparation aimeriez-vous apprendre à refaire chez vous ?"
    elif "concert" in subject:
        intro = f"À Nyons, le {title[0].lower() + title[1:]} a lieu {period}."
        why = "Assister à ce concert, c’est prendre le temps d’écouter les musiciens en direct. Gardez les horaires et l’adresse sous la main pour rejoindre le lieu du concert avant le début."
        if "élèves" in description or "élève" in description:
            why = "Ce rendez-vous permet d’écouter les élèves et de découvrir le travail mené depuis la rentrée. Une autre manière de connaître l’école de musique, à travers ceux qui y apprennent et ceux qui les accompagnent."
        question = "Avez-vous déjà assisté à un concert de cette école de musique ?" if "école" in subject else "Qu’aimeriez-vous retrouver dans ce concert ?"
    elif "conférence" in subject:
        intro = f"À Nyons, {title} est au programme {period}."
        why = "Le sujet de cette conférence vous intéresse ? Le programme ci-dessus permet de préparer votre écoute et de noter les questions que vous aimeriez approfondir."
        question = "Quelle question aimeriez-vous approfondir pendant cette conférence ?"
    else:
        intro = f"{title} est annoncé à Nyons {period}."
        why = "Pour préparer votre sortie, retrouvez ci-dessus le programme annoncé et les coordonnées de l’organisation. Pensez à noter l’horaire et le lieu avant de partir."
        question = f"Qu’aimeriez-vous découvrir lors de « {title} » ?"
    if summary:
        intro += " " + summary
    return {
        "seo_title": title if "nyons" in subject else f"{title} à Nyons",
        "meta_description": f"{title} : {clean(practical.get('date_time')) or when}. {clean(practical.get('location_name')) or clean(practical.get('address'))}",
        "intro": intro,
        "story": description or summary or title,
        "why_it_matters": why,
        "practical": practical_text(practical, when),
        "reader_question": question,
        "_fallback": True,
    }
