
import logging


# TODO Move these constants into some other file
from clarity_ext_scripts.covid.partner_api_client import \
    COVID_RESPONSE_NEGATIVE, COVID_RESPONSE_POSITIVE

DIAGNOSIS_RESULT_KEY = "diagnosis_result"

log = logging.getLogger(__name__)

FAILED_BY_INTERNAL_CONTROL = "failed_by_internal_control"
FAILED_BY_TOO_HIGH_COVID_VALUE = "failed_by_too_high_covid_value"
FAILED_BY_REVIEW = "failed_by_review"
FAILED_ENTIRE_PLATE_BY_FAILED_EXTERNAL_CONTROL = "failed_entire_plate_by_failed_external_control"

FAILED_STATES = {FAILED_BY_INTERNAL_CONTROL,
                 FAILED_BY_TOO_HIGH_COVID_VALUE,
                 FAILED_ENTIRE_PLATE_BY_FAILED_EXTERNAL_CONTROL,
                 FAILED_BY_REVIEW}


class AnalysisServiceException(Exception):
    pass


class MultipleAnalysisErrors(AnalysisServiceException):
    pass


class PositiveControlWasNegative(AnalysisServiceException):
    pass


class NegativeControlWasPositive(AnalysisServiceException):
    pass


class FailedControl(AnalysisServiceException):
    pass


class RTPCRAnalysisService(object):
    """
    Create a new RTPCRAnalysis Service:
        RTPCRAnalysisService(covid_reporter_key="FAM-CT",
                             internal_control_reporter_key="HEX-CT")
    """

    INTERNAL_CONTROL_THRESHOLD = 32
    COVID_CONTROL_THRESHOLD = 38

    def __init__(self, covid_reporter_key, internal_control_reporter_key):
        self._covid_reporter_key = covid_reporter_key
        self.internal_control_reporter_key = internal_control_reporter_key

    # These are notes on what Maike said about the analysis
    # Understanding of the analysis criterias
    # FAM = COVID, HEX = Human internal control
    # Positive if CT(FAM) = <=38
    # Failed  if CT(FAM)= >38
    # Negative if CT(FAM) = 0 and CT(HEX) = <=32
    # Failed if CT(FAM) = 0 and CT(HEX) = >32
    # Failed if CT(FAM) = 0 and CT(HEX/VIC) = 0

    # TODO Later we might have to account for giving two trails over 38 as positive.

    # POS Control
    # FAM=0 and VIC=0 => FAIL
    # NEG Control
    # FAM=0 and VIC=0 => NEG
    # SAMPLE
    # FAM=0 and VIC=0 => FAIL

    def _analyze_sample(self, sample, is_neg_control=False):
        covid_ct = sample[self._covid_reporter_key]
        internal_control_ct = sample[self.internal_control_reporter_key]
        if covid_ct == 0 and internal_control_ct == 0:
            if is_neg_control:
                return COVID_RESPONSE_NEGATIVE
            else:
                return FAILED_BY_INTERNAL_CONTROL
        elif covid_ct == 0 and internal_control_ct <= self.INTERNAL_CONTROL_THRESHOLD:
            return COVID_RESPONSE_NEGATIVE
        elif covid_ct == 0 and internal_control_ct > self.INTERNAL_CONTROL_THRESHOLD:
            return FAILED_BY_INTERNAL_CONTROL
        elif covid_ct > self.COVID_CONTROL_THRESHOLD:
            return FAILED_BY_TOO_HIGH_COVID_VALUE
        elif 0 < covid_ct <= self.COVID_CONTROL_THRESHOLD:
            return COVID_RESPONSE_POSITIVE
        else:
            raise AssertionError(
                "Got CT-value for {}: {} and CT-value for {}: {}.".format(self._covid_reporter_key,
                                                                          covid_ct,
                                                                          self.internal_control_reporter_key,
                                                                          internal_control_ct))

    def _analyze_positive_control(self, control):
        return self._analyze_sample(control, is_neg_control=False)

    def _analyze_negative_control(self, control):
        return self._analyze_sample(control, is_neg_control=True)

    def _analyze_controls(self, positive_controls, negative_controls):
        errors = []
        control_results = []
        for pos_control in positive_controls:
            res = self._analyze_positive_control(pos_control)
            control_results.append({"id": pos_control["id"],
                                    DIAGNOSIS_RESULT_KEY: res})

            if res == COVID_RESPONSE_NEGATIVE:
                errors.append(PositiveControlWasNegative(
                    "Positive control sample: {} was negative for covid-19".format(pos_control["id"])))
            if res in FAILED_STATES:
                errors.append(FailedControl("Positive control sample: {} failed with status: {}".format(pos_control["id"],
                                                                                                        res)))
        for neg_control in negative_controls:
            res = self._analyze_negative_control(neg_control)
            control_results.append({"id": neg_control["id"],
                                    DIAGNOSIS_RESULT_KEY: res})

            if res == COVID_RESPONSE_POSITIVE:
                errors.append(NegativeControlWasPositive(
                    "Negative control sample: {} was positive for covid-19".format(
                        neg_control["id"])))
            if res in FAILED_STATES:
                errors.append(FailedControl("Negative control sample: {} failed with status: {}".format(pos_control["id"],
                                                                                                        res)))

        if errors:
            for e in errors:
                log.info("Error in covid result: " + e.message)

        return control_results, errors

    def analyze_samples(self, positive_controls, negative_controls, samples):
        """
        This assumes all controls and samples are from the same plate.
        All samples, and controls should be submitted as dict-like objects on the format:
         {"id": "<sample id>", "FAM-CT": <value as numeric>, "HEX-Ct": <value as numeric>}

        The method will return a generator of objects on the format:
         {"id": "<same as sample id above>",
             "diagnosis_result": <CONST COVID RESPONSE>}
        """

        # TODO Should we validate that there are controls on the plate?
        if not positive_controls:
            raise AssertionError(
                "Positive controls are missing from input. They are mandatory!")

        if not negative_controls:
            raise AssertionError(
                "Negative controls are missing from input. They are mandatory!")

        # If controls fail, fail all samples on plate.
        control_results, errors = self._analyze_controls(
            positive_controls, negative_controls)

        for control in control_results:
            yield control

        # If there were errors in the controls we will fail the entire plate.
        if errors:
            for sample in samples:
                yield {"id": sample["id"],
                       DIAGNOSIS_RESULT_KEY: FAILED_ENTIRE_PLATE_BY_FAILED_EXTERNAL_CONTROL}
        # Check samples
        else:
            for sample in samples:
                result = self._analyze_sample(sample)
                yield {"id": sample["id"], DIAGNOSIS_RESULT_KEY: result}


class ABI7500RTPCRAnalysisService(RTPCRAnalysisService):
    def __init__(self):
        super(ABI7500RTPCRAnalysisService, self).__init__(
            covid_reporter_key="FAM-CT", internal_control_reporter_key="HEX-CT")


class QuantStudio7AnalysisService(RTPCRAnalysisService):
    def __init__(self):
        super(QuantStudio7AnalysisService, self).__init__(
            covid_reporter_key="FAM-CT", internal_control_reporter_key="VIC-CT")
