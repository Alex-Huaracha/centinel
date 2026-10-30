from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from centinel.config import get_settings
from centinel.db.models import Expense, ExpenseSource, PaymentMethod
from centinel.errors import UserError
from centinel.expenses.schemas import (
    CreateCategoryInput,
    ExpenseOrder,
    FindMerchantInput,
    GetSpendingInput,
    ListExpensesInput,
    MissingField,
    SaveExpenseInput,
    SetMerchantCategoryInput,
    SpendingGroup,
    UpdateExpenseInput,
)
from centinel.expenses.service import (
    create_category,
    find_merchant,
    get_spending,
    list_categories,
    list_expenses,
    save_expense,
    set_merchant_category,
    update_expense,
)

# Days are counted in the user's timezone.
TZ = get_settings().timezone
OCT_1 = datetime(2026, 10, 1, tzinfo=TZ)
OCT_15 = datetime(2026, 10, 15, tzinfo=TZ)
OCT_31_NIGHT = datetime(2026, 10, 31, 23, 30, tzinfo=TZ)
NOV_1 = datetime(2026, 11, 1, tzinfo=TZ)
OCTOBER = {"start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31)}


def _save(session: Session, **fields) -> None:
    save_expense(session, SaveExpenseInput(**{"currency": "PEN", **fields}))


# --- save_expense ---


def test_save_expense_creates_merchant_and_category(session: Session):
    result = save_expense(
        session,
        SaveExpenseInput(
            currency="PEN", amount=Decimal("25.50"), merchant="Tambo", category="Food"
        ),
    )

    assert result.amount == Decimal("25.50")
    assert result.currency == "PEN"
    assert result.merchant == "Tambo"
    assert result.category == "food"


def test_save_expense_without_currency_takes_the_most_used_one(session: Session):
    _save(session, amount=Decimal(1), currency="USD")
    _save(session, amount=Decimal(2), currency="MXN")
    _save(session, amount=Decimal(3), currency="MXN")

    result = save_expense(session, SaveExpenseInput(amount=Decimal(4)))

    assert result.currency == "MXN"


def test_save_expense_without_currency_or_expenses_asks_for_it(session: Session):
    with pytest.raises(UserError, match="ask the user which currency"):
        save_expense(session, SaveExpenseInput(amount=Decimal(4), merchant="Tambo"))

    assert find_merchant(session, FindMerchantInput(query="Tambo")) == []


def test_save_expense_uses_learned_merchant_category(session: Session):
    set_merchant_category(
        session, SetMerchantCategoryInput(merchant="Tambo", category="food")
    )

    result = save_expense(
        session, SaveExpenseInput(currency="PEN", amount=Decimal(10), merchant="TAMBO")
    )

    assert result.merchant == "Tambo"
    assert result.category == "food"


def test_save_expense_teaches_category_to_new_merchant(session: Session):
    _save(session, amount=Decimal(25), merchant="Bembos", category="food")

    result = save_expense(
        session, SaveExpenseInput(currency="PEN", amount=Decimal(22), merchant="Bembos")
    )

    assert result.category == "food"


def test_save_expense_keeps_merchant_learned_category(session: Session):
    _save(session, amount=Decimal(25), merchant="Tambo", category="food")
    _save(session, amount=Decimal(5), merchant="Tambo", category="transport")

    result = save_expense(
        session, SaveExpenseInput(currency="PEN", amount=Decimal(1), merchant="Tambo")
    )

    assert result.category == "food"


def test_save_expense_rejects_unknown_category(session: Session):
    with pytest.raises(UserError, match="Valid categories: food, shopping, transport"):
        save_expense(
            session,
            SaveExpenseInput(currency="PEN", amount=Decimal(10), category="pets"),
        )


def test_save_expense_rejects_duplicate_email(session: Session):
    _save(session, amount=Decimal(10), source_email_id="gmail-123")

    with pytest.raises(UserError, match="already registered"):
        _save(session, amount=Decimal(10), source_email_id="gmail-123")


def test_save_expense_sets_source_from_email_id(session: Session):
    email = save_expense(
        session,
        SaveExpenseInput(currency="PEN", amount=Decimal(10), source_email_id="g-1"),
    )
    manual = save_expense(session, SaveExpenseInput(currency="PEN", amount=Decimal(10)))

    assert session.get_one(Expense, email.id).source == ExpenseSource.EMAIL
    assert session.get_one(Expense, manual.id).source == ExpenseSource.MANUAL


@pytest.mark.parametrize(
    "fields",
    [
        {"amount": Decimal(0)},
        {"amount": Decimal("1.234")},
        {"amount": Decimal(10), "currency": "soles"},
    ],
    ids=["zero-amount", "three-decimals", "bad-currency"],
)
def test_save_expense_input_validation(fields: dict):
    with pytest.raises(ValidationError):
        SaveExpenseInput(**fields)


def test_datetime_without_offset_is_in_user_timezone():
    data = SaveExpenseInput.model_validate(
        {"amount": 1, "spent_at": "2026-10-01T12:00:00"}
    )

    assert data.spent_at == datetime(2026, 10, 1, 12, tzinfo=TZ)


def test_datetime_with_offset_is_kept():
    data = SaveExpenseInput.model_validate(
        {"amount": 1, "spent_at": "2026-10-01T12:00:00+00:00"}
    )

    assert data.spent_at == datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert data.spent_at is not None and data.spent_at.utcoffset() == timedelta(0)


# --- get_spending ---


def test_get_spending_sums_per_currency_within_period(session: Session):
    _save(session, amount=Decimal("10.10"), spent_at=OCT_1, category="food")
    _save(session, amount=Decimal("5.20"), spent_at=OCT_15, category="transport")
    _save(session, amount=Decimal(30), currency="USD", spent_at=OCT_15)
    _save(session, amount=Decimal(1), spent_at=OCT_31_NIGHT)  # end_date is inclusive
    _save(session, amount=Decimal(99), spent_at=NOV_1)

    totals = get_spending(session, GetSpendingInput(**OCTOBER)).totals

    assert [(t.currency, t.total, t.count) for t in totals] == [
        ("PEN", Decimal("16.30"), 3),
        ("USD", Decimal("30.00"), 1),
    ]


def test_get_spending_single_day_includes_the_whole_day(session: Session):
    _save(session, amount=Decimal(7), spent_at=OCT_31_NIGHT)

    day = date(2026, 10, 31)
    totals = get_spending(
        session, GetSpendingInput(start_date=day, end_date=day)
    ).totals

    assert [(t.total, t.count) for t in totals] == [(Decimal("7.00"), 1)]


def test_get_spending_rejects_end_before_start(session: Session):
    with pytest.raises(UserError, match="is before start_date"):
        get_spending(
            session,
            GetSpendingInput(start_date=date(2026, 10, 31), end_date=date(2026, 10, 1)),
        )


def test_get_spending_filters_by_category(session: Session):
    _save(session, amount=Decimal(10), spent_at=OCT_1, category="food")
    _save(session, amount=Decimal(5), spent_at=OCT_1, category="transport")

    totals = get_spending(session, GetSpendingInput(**OCTOBER, category="food")).totals

    assert [(t.total, t.count) for t in totals] == [(Decimal("10.00"), 1)]


def test_get_spending_returns_empty_lists_without_expenses(session: Session):
    result = get_spending(session, GetSpendingInput(**OCTOBER))

    assert result.totals == []
    assert result.groups == []


def test_get_spending_filters_by_merchant_and_payment_method(session: Session):
    card = PaymentMethod.DEBIT_CARD
    _save(
        session,
        amount=Decimal(10),
        spent_at=OCT_1,
        merchant="Wong",
        payment_method=card,
    )
    _save(session, amount=Decimal(4), spent_at=OCT_1, merchant="Wong")
    _save(
        session,
        amount=Decimal(7),
        spent_at=OCT_1,
        merchant="Tambo",
        payment_method=card,
    )

    by_merchant = get_spending(
        session, GetSpendingInput(**OCTOBER, merchant="won")
    ).totals
    by_both = get_spending(
        session, GetSpendingInput(**OCTOBER, merchant="won", payment_method=card)
    ).totals

    assert [(t.total, t.count) for t in by_merchant] == [(Decimal("14.00"), 2)]
    assert [(t.total, t.count) for t in by_both] == [(Decimal("10.00"), 1)]


def test_get_spending_by_category_largest_first(session: Session):
    _save(session, amount=Decimal(10), spent_at=OCT_1, category="food")
    _save(session, amount=Decimal(5), spent_at=OCT_15, category="food")
    _save(session, amount=Decimal(30), spent_at=OCT_15, category="transport")
    _save(session, amount=Decimal(2), spent_at=OCT_15)

    result = get_spending(
        session, GetSpendingInput(**OCTOBER, group_by=SpendingGroup.CATEGORY)
    )

    assert [(t.group, t.total, t.count) for t in result.groups] == [
        ("transport", Decimal("30.00"), 1),
        ("food", Decimal("15.00"), 2),
        (None, Decimal("2.00"), 1),
    ]
    # The whole period comes summed too, so the agent never adds up the groups.
    assert [(t.total, t.count) for t in result.totals] == [(Decimal("47.00"), 4)]


def test_get_spending_by_merchant_tells_apart_references(session: Session):
    _save(session, amount=Decimal(20), spent_at=OCT_1, merchant="Wong")
    _save(
        session,
        amount=Decimal(10),
        spent_at=OCT_1,
        merchant="Ana Ro*",
        merchant_reference="606",
    )
    _save(
        session,
        amount=Decimal(5),
        spent_at=OCT_1,
        merchant="Ana Ro*",
        merchant_reference="478",
    )

    totals = get_spending(
        session, GetSpendingInput(**OCTOBER, group_by=SpendingGroup.MERCHANT)
    ).groups

    assert [t.group for t in totals] == ["Wong", "Ana Ro* (606)", "Ana Ro* (478)"]


def test_get_spending_by_month_uses_the_user_timezone(session: Session):
    _save(session, amount=Decimal(1), spent_at=OCT_1)
    _save(session, amount=Decimal(2), spent_at=OCT_31_NIGHT)  # already November in UTC
    _save(session, amount=Decimal(4), spent_at=NOV_1)

    totals = get_spending(
        session,
        GetSpendingInput(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 11, 30),
            group_by=SpendingGroup.MONTH,
        ),
    ).groups

    assert [(t.group, t.total) for t in totals] == [
        ("2026-10-01", Decimal("3.00")),
        ("2026-11-01", Decimal("4.00")),
    ]


def test_get_spending_by_week_starts_on_monday(session: Session):
    _save(session, amount=Decimal(1), spent_at=OCT_1)  # Thursday
    _save(session, amount=Decimal(2), spent_at=OCT_15)  # Thursday, two weeks later

    totals = get_spending(
        session, GetSpendingInput(**OCTOBER, group_by=SpendingGroup.WEEK)
    ).groups

    assert [t.group for t in totals] == ["2026-09-28", "2026-10-12"]


# --- list_expenses ---


def test_list_expenses_most_recent_first_with_limit(session: Session):
    _save(session, amount=Decimal(1), spent_at=OCT_1)
    _save(session, amount=Decimal(2), spent_at=OCT_15)
    _save(session, amount=Decimal(3), spent_at=NOV_1)

    result = list_expenses(session, ListExpensesInput(limit=2))

    assert [e.amount for e in result] == [Decimal("3.00"), Decimal("2.00")]


def test_list_expenses_filters_by_merchant_partial_name(session: Session):
    _save(session, amount=Decimal(1), merchant="Tambo+ San Isidro")
    _save(session, amount=Decimal(2), merchant="Wong")

    result = list_expenses(session, ListExpensesInput(merchant="tambo"))

    assert [e.merchant for e in result] == ["Tambo+ San Isidro"]


def test_list_expenses_largest_first(session: Session):
    _save(session, amount=Decimal(5), spent_at=OCT_1)
    _save(session, amount=Decimal(50), spent_at=OCT_1)
    _save(session, amount=Decimal(20), spent_at=OCT_15)

    result = list_expenses(session, ListExpensesInput(order_by=ExpenseOrder.AMOUNT))

    assert [e.amount for e in result] == [Decimal(50), Decimal(20), Decimal(5)]


def test_list_expenses_missing_category_or_description(session: Session):
    _save(session, amount=Decimal(1), category="food", description="lunch")
    _save(session, amount=Decimal(2), description="taxi")
    _save(session, amount=Decimal(3), category="food")

    no_category = list_expenses(
        session, ListExpensesInput(missing=MissingField.CATEGORY)
    )
    no_description = list_expenses(
        session, ListExpensesInput(missing=MissingField.DESCRIPTION)
    )

    assert [e.amount for e in no_category] == [Decimal(2)]
    assert [e.amount for e in no_description] == [Decimal(3)]


# --- find_merchant / set_merchant_category ---


def test_find_merchant_by_partial_name(session: Session):
    set_merchant_category(
        session, SetMerchantCategoryInput(merchant="Tambo", category="food")
    )
    _save(session, amount=Decimal(1), merchant="Wong")

    result = find_merchant(session, FindMerchantInput(query="tam"))

    assert [(m.name, m.category) for m in result] == [("Tambo", "food")]


def test_set_merchant_category_backfills_uncategorized_expenses(session: Session):
    _save(session, amount=Decimal(1), merchant="Temu")
    _save(session, amount=Decimal(2), merchant="Temu")
    _save(session, amount=Decimal(3), merchant="Temu", category="food")  # keeps its own

    result = set_merchant_category(
        session, SetMerchantCategoryInput(merchant="temu", category="shopping")
    )

    assert result.expenses_updated == 2
    assert result.merchant.category == "shopping"
    categories = {
        e.amount: e.category for e in list_expenses(session, ListExpensesInput())
    }
    assert categories == {
        Decimal("1.00"): "shopping",
        Decimal("2.00"): "shopping",
        Decimal("3.00"): "food",
    }


# --- categories ---


def test_list_categories_alphabetically(session: Session):
    assert list_categories(session) == ["food", "shopping", "transport"]


def test_create_category_stores_it_in_lowercase(session: Session):
    name = create_category(session, CreateCategoryInput(name="  Pets "))

    assert name == "pets"
    assert "pets" in list_categories(session)
    _save(session, amount=Decimal(30), category="PETS")


def test_create_category_rejects_existing_name(session: Session):
    with pytest.raises(UserError, match="already exists"):
        create_category(session, CreateCategoryInput(name="Food"))


def test_create_category_rejects_blank_name():
    with pytest.raises(ValidationError):
        CreateCategoryInput(name="   ")


# --- merchant_reference ---


def test_same_masked_name_with_other_digits_is_another_merchant(session: Session):
    _save(
        session,
        amount=Decimal(10),
        merchant="Edilberto Mac*",
        merchant_reference="606",
        category="food",
    )
    _save(
        session,
        amount=Decimal(5),
        merchant="Edilberto Mac*",
        merchant_reference="112",
        category="transport",
    )

    again = save_expense(
        session,
        SaveExpenseInput(
            currency="PEN",
            amount=Decimal(1),
            merchant="edilberto mac*",
            merchant_reference="606",
        ),
    )

    assert (again.merchant, again.merchant_reference) == ("Edilberto Mac*", "606")
    assert again.category == "food"
    merchants = find_merchant(session, FindMerchantInput(query="edilberto"))
    assert {(m.reference, m.category) for m in merchants} == {
        ("606", "food"),
        ("112", "transport"),
    }


def test_merchant_without_reference_is_not_one_with_reference(session: Session):
    _save(session, amount=Decimal(10), merchant="Bembos", category="food")

    result = save_expense(
        session,
        SaveExpenseInput(
            currency="PEN", amount=Decimal(1), merchant="Bembos", merchant_reference="1"
        ),
    )

    assert result.category is None


def test_merchant_reference_requires_merchant():
    with pytest.raises(ValidationError, match="requires merchant"):
        SaveExpenseInput(currency="PEN", amount=Decimal(1), merchant_reference="606")


# --- update_expense ---


def test_update_expense_changes_only_given_fields(session: Session):
    saved = save_expense(
        session,
        SaveExpenseInput(
            currency="PEN",
            amount=Decimal(100),
            merchant="Self",
            category="shopping",
            payment_method=PaymentMethod.YAPE,
            spent_at=OCT_15,
        ),
    )

    result = update_expense(
        session, UpdateExpenseInput(id=saved.id, category="food", amount=Decimal(90))
    )

    assert (result.category, result.amount) == ("food", Decimal("90.00"))
    assert (result.merchant, result.payment_method, result.spent_at) == (
        "Self",
        PaymentMethod.YAPE,
        OCT_15,
    )


def test_update_expense_moves_it_to_another_merchant(session: Session):
    saved = save_expense(
        session, SaveExpenseInput(currency="PEN", amount=Decimal(1), merchant="A")
    )

    result = update_expense(
        session,
        UpdateExpenseInput(id=saved.id, merchant="Esther Agu*", merchant_reference="9"),
    )

    assert (result.merchant, result.merchant_reference) == ("Esther Agu*", "9")


def test_update_expense_rejects_unknown_id(session: Session):
    with pytest.raises(UserError, match="no expense with id 999"):
        update_expense(session, UpdateExpenseInput(id=999, category="food"))


def test_update_expense_rejects_unknown_category(session: Session):
    saved = save_expense(session, SaveExpenseInput(currency="PEN", amount=Decimal(1)))

    with pytest.raises(UserError, match="Unknown category"):
        update_expense(session, UpdateExpenseInput(id=saved.id, category="pets"))
