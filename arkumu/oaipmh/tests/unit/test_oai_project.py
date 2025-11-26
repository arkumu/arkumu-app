from __future__ import annotations

import pytest

from arkumu.oaipmh.oai_project import OAIProjectBuilder
from arkumu.projects import ProjectDigitalObject, ProjectInstitution, ProjectRecord


def _make_record(**kwargs) -> ProjectRecord:
    defaults = {
        'subject_id': 'proj-1',
        'uri': 'https://arkumu.example/entities/projekt/1',
        'title': 'Test Project',
        'institution': ProjectInstitution(label='FUK', code='fuk'),
        'digital_objects': [],
    }
    defaults.update(kwargs)
    return ProjectRecord(**defaults)


@pytest.fixture
def stub_s3_fixity(monkeypatch):
    """Ensure S3 harvestable org tests do not depend on fixity TSV files."""
    from arkumu.projects.services import dump_fixity_index

    original = dump_fixity_index.find_fixity

    def fake_find_fixity(org_code, candidates):
        if (org_code or "").lower().strip() != "fuk":
            return original(org_code, candidates)
        first = next((candidate for candidate in candidates if candidate), None)
        if not first:
            return None
        return dump_fixity_index.FixityRecord(
            dump_key=str(first),
            storage_key=str(first),
            checksum_or_etag="md5:stub",
            status="verified",
        )

    monkeypatch.setattr(dump_fixity_index, "find_fixity", fake_find_fixity)


@pytest.mark.usefixtures("stub_s3_fixity")
def test_builder_marks_s3_project_harvestable(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ()
    settings.OAI_S3_ROSETTA_BASE_PATHS = {}
    settings.AWS_S3_BROWSER_ENDPOINT_URL = 'https://downloads.example.org'

    builder = OAIProjectBuilder()
    record = _make_record(
        digital_objects=[
            ProjectDigitalObject(
                path='incoming/object_master.tif',
                storage_key='s3://fuk/object_master.tif',
                file_name='object_master.tif',
                content_type='image/tiff',
                size_bytes=1024,
                storage_status='completed',
                checksum='abc123',
            )
        ],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is True
    assert project.institution_code == 'fuk'
    assert len(project.digital_objects) == 1
    obj = project.digital_objects[0]
    assert obj.storage_key == 's3://fuk/object_master.tif'
    assert obj.download_href == 'https://downloads.example.org/fuk/object_master.tif'
    assert obj.preferred_location == obj.download_href
    assert obj.source == 's3'
    assert obj.harvestable is True


@pytest.mark.usefixtures("stub_s3_fixity")
def test_builder_prefers_https_download_for_s3(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ()
    settings.AWS_S3_BROWSER_ENDPOINT_URL = 'https://downloads.example.org'

    builder = OAIProjectBuilder()
    record = _make_record(
        digital_objects=[
            ProjectDigitalObject(
                path='incoming/object_master.tif',
                storage_key='s3://fuk/assets/object_master.tif',
                file_name='object_master.tif',
                content_type='image/tiff',
                storage_status='completed',
            )
        ],
    )

    project = builder.from_project_record(record)
    obj = project.digital_objects[0]
    assert obj.download_href == 'https://downloads.example.org/fuk/assets/object_master.tif'
    assert obj.preferred_location == obj.download_href
    assert obj.source == 's3'


def test_builder_resolves_khm_rosetta_path(tmp_path, settings):
    mapping = tmp_path / 'khm_paths.txt'
    rosetta_path = '/rosetta/khm/test/input/object_master.tif'
    mapping.write_text(f"{rosetta_path}\n", encoding='utf-8')

    checksum_value = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'

    settings.OAI_EXTERNAL_PATH_FILES = {'khm': str(mapping)}
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {'khm': '/rosetta/khm/test/input'}
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('khm',)

    builder = OAIProjectBuilder()
    record = _make_record(
        institution=ProjectInstitution(label='KHM', code='khm'),
        digital_objects=[
            ProjectDigitalObject(
                path='khm/object_master.tif',
                file_name='object_master.tif',
                content_type='image/tiff',
                checksum=checksum_value,
                checksum_algorithm='sha256',
            )
        ],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is True
    obj = project.digital_objects[0]
    assert obj.rosetta_path == rosetta_path
    assert obj.preferred_location == rosetta_path
    assert obj.source == 'rosetta'
    assert obj.checksum == checksum_value
    assert obj.checksum_algorithm == 'sha256'


def test_builder_resolves_hmt_prefix(tmp_path, settings):
    mapping = tmp_path / 'hmt_paths.txt'
    rosetta_path = '/rosetta/hfmt/sandbox/input/arkumu/object_master.wav'
    mapping.write_text(f"{rosetta_path}\n", encoding='utf-8')

    checksum_value = 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789'

    settings.OAI_EXTERNAL_PATH_FILES = {'hmt': str(mapping)}
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {'hmt': '/rosetta/hfmt/sandbox/input/arkumu'}
    settings.OAI_EXTERNAL_PATH_PREFIXES = {'hmt': ['/Volumes/18TB1']}
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('hmt',)

    builder = OAIProjectBuilder()
    record = _make_record(
        institution=ProjectInstitution(label='HMT', code='hmt'),
        digital_objects=[
            ProjectDigitalObject(
                path='/Volumes/18TB1/source/object_master.wav',
                file_name='object_master.wav',
                checksum=checksum_value,
                checksum_algorithm='sha256',
            )
        ],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is True
    obj = project.digital_objects[0]
    assert obj.rosetta_path == rosetta_path
    assert obj.preferred_location == rosetta_path
    assert obj.source == 'rosetta'
    assert obj.checksum == checksum_value
    assert obj.checksum_algorithm == 'sha256'


def test_builder_skips_rosetta_object_without_index(tmp_path, settings):
    mapping = tmp_path / 'hmt_paths.txt'
    mapping.write_text("/rosetta/hfmt/sandbox/input/arkumu/daten/object_master.wav\n", encoding='utf-8')

    settings.OAI_EXTERNAL_PATH_FILES = {'hmt': str(mapping)}
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {'hmt': '/rosetta/hfmt/sandbox/input/arkumu/daten'}
    settings.OAI_EXTERNAL_PATH_PREFIXES = {'hmt': ['/Volumes/18TB1']}
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('hmt',)

    from arkumu.oaipmh import path_mapping
    path_mapping._load_index.cache_clear()

    builder = OAIProjectBuilder()
    record = _make_record(
        institution=ProjectInstitution(label='HMT', code='hmt'),
        digital_objects=[
            ProjectDigitalObject(
                path='/Volumes/18TB1/source/object_missing.wav',
                file_name='object_missing.wav',
            )
        ],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is False
    assert project.digital_objects == ()


def test_builder_applies_code_alias(tmp_path, settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('hmt',)
    settings.OAI_INSTITUTION_CODE_ALIASES = {'ff8f3b0306bebf6d': 'hmt'}
    settings.OAI_INSTITUTION_LABEL_ALIASES = {}
    mapping = tmp_path / 'hmt_paths.txt'
    rosetta_path = '/rosetta/hfmt/sandbox/input/arkumu/object_master.wav'
    mapping.write_text(f"{rosetta_path}\n", encoding='utf-8')
    settings.OAI_EXTERNAL_PATH_FILES = {'hmt': str(mapping)}
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {'hmt': '/rosetta/hfmt/sandbox/input/arkumu'}

    from arkumu.oaipmh import path_mapping
    path_mapping._load_index.cache_clear()

    builder = OAIProjectBuilder()
    record = _make_record(
        institution=ProjectInstitution(label='Hochschule für Musik und Tanz Köln', code='ff8f3b0306bebf6d'),
        digital_objects=[
            ProjectDigitalObject(
                path=rosetta_path,
                file_name='object_master.wav',
                checksum='b' * 64,
                checksum_algorithm='sha256',
            )
        ],
    )

    project = builder.from_project_record(record)
    assert project.institution_code == 'hmt'
    assert project.digital_objects[0].rosetta_path == rosetta_path


@pytest.mark.usefixtures("stub_s3_fixity")
def test_builder_filters_non_harvestable_status(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ()
    settings.OAI_S3_ROSETTA_BASE_PATHS = {}

    builder = OAIProjectBuilder()
    record = _make_record(
        digital_objects=[
            ProjectDigitalObject(
                path='incoming/object_master.tif',
                storage_key='s3://fuk/object_master.tif',
                storage_status='pending',
            )
        ],
    )

    project = builder.from_project_record(record)
    assert project.harvestable is False
    assert all(obj.harvestable is False for obj in project.digital_objects)


def test_builder_accepts_existing_rosetta_path(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('khm',)
    settings.OAI_EXTERNAL_PATH_FILES = {}
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {}

    from arkumu.oaipmh import path_mapping
    path_mapping._load_index.cache_clear()

    builder = OAIProjectBuilder()
    rosetta_path = '/rosetta/khm/sandbox/input/arkumu/daten/object_master.tif'
    record = _make_record(
        institution=ProjectInstitution(label='KHM', code='khm'),
        digital_objects=[
            ProjectDigitalObject(
                path=rosetta_path,
                file_name='object_master.tif',
                content_type='image/tiff',
                checksum='c' * 64,
                checksum_algorithm='sha256',
            )
        ],
    )

    project = builder.from_project_record(record)

    obj = project.digital_objects[0]
    assert obj.rosetta_path == rosetta_path
    assert obj.preferred_location == rosetta_path
    assert obj.harvestable is True


@pytest.mark.usefixtures("stub_s3_fixity")
def test_builder_primary_object_and_mime_types(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)
    settings.OAI_S3_ROSETTA_BASE_PATHS = {}
    builder = OAIProjectBuilder()

    record = _make_record(
        digital_objects=[
            ProjectDigitalObject(
                path='incoming/object_master.tif',
                storage_key='s3://fuk/object_master.tif',
                file_name='object_master.tif',
                content_type='image/tiff',
                storage_status='completed',
            ),
            ProjectDigitalObject(
                path='incoming/object_preview.jpg',
                storage_key='s3://fuk/object_preview.jpg',
                file_name='object_preview.jpg',
                content_type='image/jpeg',
                storage_status='completed',
            ),
        ],
    )

    project = builder.from_project_record(record)
    primary = project.primary_object()
    assert primary is not None
    assert primary.file_name == 'object_master.tif'
    assert tuple(project.mime_types()) == ('image/tiff', 'image/jpeg')


def test_builder_omits_filtered_digital_objects(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('khm',)
    settings.OAI_EXTERNAL_PATH_FILES = {}

    builder = OAIProjectBuilder()
    keep_object = ProjectDigitalObject(
        path='/rosetta/khm/sandbox/input/arkumu/daten/object_keep.tif',
        resource_id='keep-1',
    )
    drop_object = ProjectDigitalObject(
        path='/rosetta/khm/sandbox/input/arkumu/daten/object_drop.tif',
        resource_id='drop-1',
    )
    record = _make_record(
        institution=ProjectInstitution(label='KHM', code='khm'),
        digital_objects=[drop_object, keep_object],
        filtered_digital_object_ids=['drop-1'],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is True
    assert len(project.digital_objects) == 1
    obj = project.digital_objects[0]
    assert obj.rosetta_path == '/rosetta/khm/sandbox/input/arkumu/daten/object_keep.tif'
    assert project.record.harvestable is True
    assert project.record.filtered_digital_object_ids == ['drop-1']


def test_builder_marks_reference_only_when_all_objects_filtered(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('khm',)
    settings.OAI_EXTERNAL_PATH_FILES = {}

    builder = OAIProjectBuilder()
    drop_object = ProjectDigitalObject(
        path='/rosetta/khm/sandbox/input/arkumu/daten/object_drop.tif',
        resource_id='drop-1',
    )
    record = _make_record(
        institution=ProjectInstitution(label='KHM', code='khm'),
        digital_objects=[drop_object],
        filtered_digital_object_ids=['drop-1'],
        ownership_filtered=True,
    )

    project = builder.from_project_record(record)

    assert project.harvestable is False
    assert project.digital_objects == ()
    assert project.record.harvestable is False
    assert project.record.reference_only is True


def test_builder_suppresses_hmt_overarching_digital_objects(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('hmt',)
    settings.OAI_EXTERNAL_PATH_FILES = {}
    settings.OAI_INSTITUTION_CODE_ALIASES = {'ff8f3b0306bebf6d': 'hmt'}
    from arkumu.oaipmh import path_mapping
    path_mapping._load_index.cache_clear()

    builder = OAIProjectBuilder()
    record = _make_record(
        uri='https://arkumu.example/entities/00-hfm-projekte/hfmt-ow-44',
        institution=ProjectInstitution(label='Hochschule für Musik und Tanz Köln', code='ff8f3b0306bebf6d'),
        digital_objects=[
            ProjectDigitalObject(
                path='/rosetta/hfmt/sandbox/input/arkumu/daten/object_master.wav',
                file_name='object_master.wav',
                checksum='a' * 64,
                checksum_algorithm='sha256',
            )
        ],
        reference_project_uris=[
            'https://arkumu.example/entities/00-hfm-projekte/hfmt-tb-bib-9',
            'https://arkumu.example/entities/00-hfm-projekte/hfmt-tb-bib-13',
        ],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is False
    assert project.digital_objects == ()
    assert project.record.reference_only is True


def test_builder_filters_hmt_mp3_objects(tmp_path, settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ()
    settings.OAI_ROSETTA_HARVESTABLE_ORGS = ('hmt',)
    mapping = tmp_path / 'hmt_paths.txt'
    wav_path = '/rosetta/hfmt/sandbox/input/arkumu/daten/object_master.wav'
    mp3_path = '/rosetta/hfmt/sandbox/input/arkumu/daten/object_master.mp3'
    mapping.write_text(f"{wav_path}\n{mp3_path}\n", encoding='utf-8')
    settings.OAI_EXTERNAL_PATH_FILES = {'hmt': str(mapping)}
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {'hmt': '/rosetta/hfmt/sandbox/input/arkumu/daten'}

    from arkumu.oaipmh import path_mapping
    path_mapping._load_index.cache_clear()

    builder = OAIProjectBuilder()
    record = _make_record(
        institution=ProjectInstitution(label='HMT', code='hmt'),
        digital_objects=[
            ProjectDigitalObject(
                path=mp3_path,
                file_name='object_master.mp3',
                checksum='d' * 64,
                checksum_algorithm='sha256',
            ),
            ProjectDigitalObject(
                path=wav_path,
                file_name='object_master.wav',
                checksum='e' * 64,
                checksum_algorithm='sha256',
            ),
        ],
    )

    project = builder.from_project_record(record)

    assert project.harvestable is True
    assert len(project.digital_objects) == 1
    obj = project.digital_objects[0]
    assert obj.rosetta_path == wav_path
    assert obj.file_name == 'object_master.wav'


@pytest.mark.usefixtures("stub_s3_fixity")
def test_builder_deduplicates_by_normalized_location(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)
    settings.OAI_S3_ROSETTA_BASE_PATHS = {}
    builder = OAIProjectBuilder()

    record = _make_record(
        digital_objects=[
            ProjectDigitalObject(
                path='incoming/object_master.tif',
                storage_key='s3://fuk/object_master.tif',
                file_name='object_master.tif',
                content_type='image/tiff',
                storage_status='completed',
            ),
            ProjectDigitalObject(
                path='incoming/object_master_duplicate.tif',
                storage_key='s3://fuk/object_master.tif',
                file_name='object_master_duplicate.tif',
                content_type='image/tiff',
                storage_status='completed',
            ),
        ],
    )

    project = builder.from_project_record(record)
    assert len(project.digital_objects) == 1
    assert project.digital_objects[0].storage_key == 's3://fuk/object_master.tif'


@pytest.mark.usefixtures("stub_s3_fixity")
def test_builder_ignores_metadata_only_objects(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ('fuk',)
    settings.OAI_S3_ROSETTA_BASE_PATHS = {}
    builder = OAIProjectBuilder()

    record = _make_record(
        digital_objects=[
            ProjectDigitalObject(
                path='metadata/Sprache.csv',
                storage_key='metadata/Sprache.csv',
                storage_status='completed',
            ),
            ProjectDigitalObject(
                path='data/fuk/object_master.tif',
                storage_key='data/fuk/object_master.tif',
                storage_status='completed',
                content_type='image/tiff',
            ),
        ],
    )

    project = builder.from_project_record(record)
    assert len(project.digital_objects) == 1
    assert project.digital_objects[0].storage_key == 'data/fuk/object_master.tif'
