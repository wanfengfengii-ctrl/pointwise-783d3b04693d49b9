import unittest

import prescription_sample
from review.prescription import PrescriptionRequest


class PrescriptionSampleTests(unittest.TestCase):
    def test_sample_requests(self):
        cases = prescription_sample.load_cases()
        signed = prescription_sample.verify_prescriptions(cases)
        self.assertEqual(
            [(prescription.status, str(prescription.energy) if prescription.energy is not None else None)
             for _, _, prescription in signed],
            [('over_threshold', '4/3'), ('executable', '1/3'),
             ('no_finite', None), ('executable', '1'),
             ('executable', '1')],
        )

    def test_commit_failure_leaves_no_draft(self):
        prescription_sample.verify_commit_failure()

    def test_v1_regression_still_passes(self):
        prescription_sample.verify_v1(prescription_sample.load_cases())


if __name__ == '__main__':
    unittest.main()
