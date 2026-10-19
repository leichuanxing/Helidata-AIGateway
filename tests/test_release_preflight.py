import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('release_check',Path(__file__).resolve().parents[1]/'scripts/check_release.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ReleasePreflightTests(unittest.TestCase):
    def test_rejects_crlf_or_bom_but_accepts_lf(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);script=root/'start.sh'
            for data in (b'#!/bin/bash\r\ntrue\r\n',b'\xef\xbb\xbf#!/bin/bash\n'):
                script.write_bytes(data)
                with self.assertRaises(ValueError):module.check_shell_files(root)
            script.write_bytes(b'#!/bin/bash\ntrue\n');module.check_shell_files(root)
