import re
from clarity_ext.service.file_service import Csv
from clarity_ext.domain.validation import UsageError
from clarity_ext.utils import single

BIOBANK_FILE_3_COLUMN_HEADER = ['well', 'biobank_barcode', 'plate_barcode']
BIOBANK_FILE_4_COLUMN_HEADER = ['well', 'biobank_barcode', 'some text', 'plate_barcode']
RAW_BIOANK_LIST = "Raw biobank list"


class FetchBiobankBarcodes(object):
    """
    This is intended to be part of create samples script. By injecting context,
    it might be tested in isolation by creating a dummy script.
    """

    def __init__(self, context):
        self.context = context
        self.barcode_by_sample_code = None

    def execute(self):
        """
        Just for testing, validate() and map_barcodes() are called separately from
        different scripts
        """
        self.validate()
        self.barcode_by_sample_code =\
            self.biobank_barcode_by_sample_referral_code()
        self._print(self.barcode_by_sample_code)

    def validate(self):
        try:
            file_stream = self.context.local_shared_file(RAW_BIOANK_LIST)
        except IOError:
            raise UsageError("Please upload the file to '{}' before proceeding!"
                             .format(RAW_BIOANK_LIST))

        biobank_info_by_well_barcode = self._build_biobank_info_by_well_barcode(file_stream)
        plate_barcodes = {
            biobank_info_by_well_barcode[key]['plate_barcode']
            for key in biobank_info_by_well_barcode
        }
        if len(plate_barcodes) > 1:
            raise UsageError("There are more than one destination plates the file in '{}'!"
                             .format(RAW_BIOANK_LIST))

        # Validate that sample list file has plate barcode as name
        filenames = self.context.file_service.list_filenames('Raw sample list')
        base_names = [n.split('.')[0] for n in filenames]
        plate_barcode = single(list(plate_barcodes))
        if plate_barcode not in base_names:
            raise UsageError(
                "The 'Raw sample list' name is not matching with the plate "
                "barcode in '{}', {}".format(RAW_BIOANK_LIST, plate_barcode))

        file_stream2 = self.context.local_shared_file('Raw sample list')
        sample_info_by_well_barcode = \
            self._build_sample_info_by_well_barcode(file_stream2, plate_barcode)

        # Validate that 'NO TUBE' entries in biobank file is empty in sample list
        sample_matrix_keys = [k for k in sample_info_by_well_barcode]
        for key in biobank_info_by_well_barcode:
            if biobank_info_by_well_barcode[key]['biobank_barcode'] == 'NO TUBE' \
                    and key in sample_matrix_keys \
                    and sample_info_by_well_barcode[key]['Sample Id']:
                biobank_well = biobank_info_by_well_barcode[key]['well']
                sample_list_well = sample_info_by_well_barcode[key]['Position']
                raise UsageError(
                    "There is an empty entry in the biobank barcode file "
                    "that is not empty in the sample list file, "
                    "biobank well: {}, sample list well: {}"
                    .format(biobank_well, sample_list_well))

    def biobank_barcode_by_sample_referral_code(self):
        file_stream = self.context.local_shared_file(RAW_BIOANK_LIST)
        biobank_matrix = self._build_biobank_info_by_well_barcode(file_stream)
        plate_barcode = self._plate_barcode_from(biobank_matrix)
        file_stream2 = self.context.local_shared_file('Raw sample list')
        sample_matrix = self._build_sample_info_by_well_barcode(file_stream2, plate_barcode)
        barcode_map = dict()
        for key in sample_matrix:
            if biobank_matrix[key]['biobank_barcode'] == 'NO TUBE':
                continue
            biobank_barcode = biobank_matrix[key]['biobank_barcode']
            sample_referal_code = sample_matrix[key]['Sample Id']
            barcode_map[sample_referal_code] = biobank_barcode

        return barcode_map

    def _end_of_file(self, line, stop_criteria):
        stop_matches = [v for v in line.values if stop_criteria in v]
        return len(stop_matches) > 0

    def _build_sample_info_by_well_barcode(self, file_stream, plate_barcode):
        csv = Csv(file_stream)
        sample_info_by_well_barcode = dict()
        pattern = re.compile(r"(?P<row>[A-Z])(?P<col>[0-9]+)")
        stop_criteria = "Sample Tracking Report Name"
        for line in csv:
            if self._end_of_file(line, stop_criteria):
                break
            trimmed_row = map(str.strip, line.values)
            row_as_dict = dict(zip(csv.header, trimmed_row))
            well_robot_format = line['Position']
            m = pattern.match(well_robot_format)
            if m is None:
                continue
            tokens = m.groupdict()
            well_default_format = '{}{}'.format(tokens['row'], int(tokens['col']))
            sample_info_by_well_barcode[
                self._biobank_key(well_default_format, plate_barcode)] = row_as_dict
        return sample_info_by_well_barcode

    def _print(self, var):
        from pprint import pprint
        pprint(var)

    def _decide_biobank_header(self, split_row):
        if len(split_row) == len(BIOBANK_FILE_3_COLUMN_HEADER):
            return BIOBANK_FILE_3_COLUMN_HEADER
        elif len(split_row) == len(BIOBANK_FILE_4_COLUMN_HEADER):
            return BIOBANK_FILE_4_COLUMN_HEADER
        else:
            raise UsageError("Unknown format of the '{}'".format(RAW_BIOANK_LIST))

    def _build_biobank_info_by_well_barcode(self, file_stream):
        contents = file_stream.read()
        rows = contents.split('\n')
        biobank_info_by_well_barcode = dict()
        header = None
        for row in rows:
            split_row = row.split(",")
            if header is None:
                header = self._decide_biobank_header(split_row)
            if len(split_row) != len(header):
                continue
            trimmed_row = map(str.strip, split_row)
            row_as_dict = dict(zip(header, trimmed_row))
            well = row_as_dict['well']
            plate_barcode = row_as_dict['plate_barcode']
            biobank_info_by_well_barcode[self._biobank_key(well, plate_barcode)] = row_as_dict
        return biobank_info_by_well_barcode

    def _plate_barcode_from(self, biobank_matrix):
        any_key = [k for k in biobank_matrix][0]
        return biobank_matrix[any_key]['plate_barcode']

    def _biobank_key(self, well, plate_barcode):
        return '{}_{}'.format(well, plate_barcode)
