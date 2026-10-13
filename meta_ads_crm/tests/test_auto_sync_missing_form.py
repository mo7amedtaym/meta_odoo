from pathlib import Path
import unittest


MODULE_ROOT = Path(__file__).resolve().parents[1]


class TestMissingFormAutoSyncWiring(unittest.TestCase):
    def test_page_exposes_single_form_sync_helper(self):
        source = (MODULE_ROOT / 'models' / 'meta_page.py').read_text(encoding='utf-8')
        self.assertIn('def _sync_lead_form_by_meta_id(', source)
        self.assertIn("'fields': 'id,name,status,locale,questions'", source)

    def test_lead_log_attempts_auto_sync_before_missing_form_error(self):
        source = (MODULE_ROOT / 'models' / 'meta_lead_log.py').read_text(encoding='utf-8')
        auto_sync_call = '._sync_lead_form_by_meta_id('
        old_error = 'No linked lead form. Create/sync a meta.lead.form record'
        self.assertIn(auto_sync_call, source)
        self.assertIn(old_error, source)
        self.assertLess(source.index(auto_sync_call), source.index(old_error))


if __name__ == '__main__':
    unittest.main()
