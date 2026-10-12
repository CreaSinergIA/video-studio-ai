"""Seguridad y robustez del almacenamiento (sin servidor)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from app.services import storage as st


def test_resolve_inside_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert st.resolve_inside(root, "projects/a/b.mp4") == (root / "projects/a/b.mp4").resolve()
    for bad in ("../x", "projects/../../x", "/etc/passwd", "", "a/\x00b"):
        with pytest.raises(st.StorageError):
            st.resolve_inside(root, bad)


def test_resolve_inside_blocks_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(st.StorageError):
        st.resolve_inside(root, "link/secret.txt")


def test_sanitize_filename() -> None:
    assert st.sanitize_filename("../../etc/passwd") == "passwd"
    assert st.sanitize_filename('mi:video*"raro"?.MOV') == "mi_video__raro__.mov"
    assert st.sanitize_filename("...") == "video"
    assert st.sanitize_filename("Canción ñandú.mp4") == "Canción ñandú.mp4"
    long_name = "a" * 400 + ".mp4"
    assert len(st.sanitize_filename(long_name)) <= 150
    assert st.sanitize_filename(long_name).endswith(".mp4")


def test_normalize_user_path_requires_absolute() -> None:
    with pytest.raises(st.StorageError):
        st.normalize_user_path("relativa/carpeta")
    with pytest.raises(st.StorageError):
        st.normalize_user_path("   ")
    assert st.normalize_user_path("/tmp/../tmp/x") == Path("/tmp/x")


def test_initialize_creates_only_last_level(tmp_path: Path) -> None:
    with pytest.raises(st.StorageError):
        st.initialize_root(str(tmp_path / "no" / "existe" / "VideoStudio"))
    assert not (tmp_path / "no").exists()
    root, marker = st.initialize_root(str(tmp_path / "VideoStudio"))
    assert (root / st.MARKER_NAME).is_file()
    assert (root / "projects").is_dir() and (root / "cache" / "uploads").is_dir()
    # Re-inicializar conserva el mismo id.
    _, again = st.initialize_root(str(root))
    assert again["storage_id"] == marker["storage_id"]


def test_disconnected_volume_is_detected_without_creating_dirs() -> None:
    root = Path("/Volumes/__vsa_disco_inexistente__/VideoStudio")
    status = st.check_root(root, "stg_x")
    assert not status.available
    assert status.code == "volume_disconnected"
    report = st.inspect_candidate(str(root))
    assert not report.can_use
    with pytest.raises(st.StorageError):
        st.initialize_root(str(root))
    assert not root.parent.exists()


def test_check_root_marker_rules(tmp_path: Path) -> None:
    root = tmp_path / "VideoStudio"
    root.mkdir()
    assert st.check_root(root, "stg_a").code == "marker_missing"
    (root / st.MARKER_NAME).write_text(json.dumps({"storage_id": "stg_b"}))
    assert st.check_root(root, "stg_a").code == "marker_mismatch"
    status = st.check_root(root, "stg_b", write_test=True)
    assert status.available and status.writable and status.free_bytes


def test_candidate_warns_on_non_empty_folder(tmp_path: Path) -> None:
    (tmp_path / "otro_archivo.txt").write_text("x")
    report = st.inspect_candidate(str(tmp_path))
    assert report.can_use
    assert report.suggested_path == str(tmp_path / "VideoStudio")
    assert any("subcarpeta" in w for w in report.warnings)


def test_remove_project_dir_safety(tmp_path: Path) -> None:
    root, _ = st.initialize_root(str(tmp_path / "VS"))
    project = root / "projects" / "p1"
    st.ensure_project_dirs(project)
    (project / "originals" / "a.mp4").write_bytes(b"x")
    # Sin manifiesto: no se borra.
    with pytest.raises(st.StorageError):
        st.remove_project_dir(root, "projects/p1", "prj_1")
    st.atomic_write_json(project / st.PROJECT_MANIFEST, {"project_id": "prj_otro"})
    with pytest.raises(st.StorageError):
        st.remove_project_dir(root, "projects/p1", "prj_1")
    # Fuera de projects/: nunca.
    with pytest.raises(st.StorageError):
        st.remove_project_dir(root, "cache", "prj_1")
    with pytest.raises(st.StorageError):
        st.remove_project_dir(root, "../..", "prj_1")
    st.atomic_write_json(project / st.PROJECT_MANIFEST, {"project_id": "prj_1"})
    assert st.remove_project_dir(root, "projects/p1", "prj_1") is True
    assert not project.exists()
    assert (root / st.MARKER_NAME).exists()


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    st.atomic_write_json(target, {"a": 1})
    st.atomic_write_json(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_cleanup_stale_uploads(tmp_path: Path) -> None:
    root, _ = st.initialize_root(str(tmp_path / "VS"))
    partial = root / st.UPLOADS_DIR / "upl_x.partial"
    partial.write_bytes(b"incompleto")
    keep = root / st.UPLOADS_DIR / "otro.txt"
    keep.write_text("no tocar")
    assert st.cleanup_stale_uploads(root, max_age_seconds=3600) == 0
    assert st.cleanup_stale_uploads(root, max_age_seconds=0) == 1
    assert not partial.exists() and keep.exists()


def test_require_space(tmp_path: Path) -> None:
    st.require_space(tmp_path, 1024)
    with pytest.raises(st.StorageError) as exc:
        st.require_space(tmp_path, 10**18)
    assert exc.value.code == "insufficient_space"


@pytest.mark.skipif(
    not os.environ.get("VSA_TEST_EXFAT_DIR"),
    reason="Define VSA_TEST_EXFAT_DIR con una carpeta en un volumen exFAT/FAT para esta prueba",
)
def test_remove_project_dir_on_exfat_with_appledouble() -> None:
    """En exFAT, macOS crea y borra por su cuenta archivos AppleDouble (._*)."""
    base = Path(os.environ["VSA_TEST_EXFAT_DIR"]) / f"vsa-test-{os.getpid()}"
    base.mkdir()
    try:
        root, _ = st.initialize_root(str(base / "VS"))
        project = root / "projects" / "p1"
        st.ensure_project_dirs(project)
        for i in range(5):
            f = project / "frames" / f"f{i}.jpg"
            f.write_bytes(b"x" * 1000)
            os.setxattr(f, "com.example.vsa", b"1") if hasattr(os, "setxattr") else None
        st.atomic_write_json(project / st.PROJECT_MANIFEST, {"project_id": "prj_1"})
        assert st.remove_project_dir(root, "projects/p1", "prj_1") is True
        assert not project.exists()
        assert not [p for p in (root / "cache" / "trash").iterdir() if not p.name.startswith("._")]
    finally:
        shutil.rmtree(base, ignore_errors=True)
