import csv
import pytest
from tgs.core import parse_links, Ledger


def test_links():
    links = parse_links('@Example\nhttps://t.me/example/\ntelegram.me/+Ab_c-12\nhttps://t.me/joinchat/Ab_c-12')
    assert len(links) == 2
    assert links[1] == ('invite:Ab_c-12', 'Ab_c-12', True)


@pytest.mark.parametrize('link', ['http://t.me/example', 'https://evil.com/example', 'https://t.me/example/123', 'https://t.me/c/123', 'https://t.me/+'])
def test_bad_links(link):
    with pytest.raises(ValueError): parse_links(link)


def test_durable_ambiguous_attempt(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    ledger = Ledger(path)
    ledger.record(123, 'Привет 🦊\nМир', 'начато')
    ledger.db.close()
    reopened = Ledger(path)
    assert reopened.previous(123, 'Привет 🦊\nМир') == ('начато',)
    assert reopened.previous(456, 'Привет 🦊\nМир') is None
    reopened.record(123, 'Привет 🦊\nМир', 'отправлено', '=formula')
    target = tmp_path / 'report.csv'
    reopened.export(target)
    rows = list(csv.reader(target.open(encoding='utf-8-sig')))
    assert rows[-1][-1] == "'=formula"
    assert 'Привет' not in target.read_text(encoding='utf-8-sig')
