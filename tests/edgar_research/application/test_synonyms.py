from app.edgar_research.application.synonyms import with_filer_terms


def test_plain_question_is_unchanged():
    q = "What was Accenture's revenue in fiscal 2025?"
    assert with_filer_terms(q) == q


def test_contingent_liabilities_adds_the_note_title():
    out = with_filer_terms("What contingent liabilities does Broadcom disclose?")
    assert out.startswith("What contingent liabilities does Broadcom disclose? ")
    assert "commitments and contingencies" in out


def test_buyback_spellings():
    for q in ("How large were the buybacks?", "Any share buyback?", "Buy-back plans", "buy back"):
        assert "repurchases of common stock" in with_filer_terms(q)


def test_each_matched_term_adds_once():
    out = with_filer_terms("supply chain and supply chains, plus EBITDA")
    assert out.count("third-party manufacturers") == 1
    assert "depreciation and amortization" in out


def test_moat_is_a_whole_word():
    assert with_filer_terms("Is the moated castle relevant?") == "Is the moated castle relevant?"
