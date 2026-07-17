"""Tests for IBM documentation parser."""

from ceph_doc_kb.indexer.ibm_parser import (
    _detect_component_from_topic,
    _split_into_sections,
    parse_ibm_page,
    extract_code_examples_from_page,
)


SAMPLE_IBM_HTML = """<!DOCTYPE html SYSTEM "about:legacy-compat">
<html lang="en-us"><head>
<title>Bootstrapping a new storage cluster</title>
</head><body>
<main role="main"><article role="article">
<h1 class="title topictitle1">Bootstrapping a new storage cluster</h1>
<div class="body taskbody">
<p class="shortdesc">Use the <code class="ph codeph">cephadm</code> utility to bootstrap a new storage cluster.</p>
<section class="section prereq">
<h2 class="sectiontitle">Before you begin</h2>
<p>Make sure that you have the following prerequisites in place:</p>
<ul class="ul">
<li class="li">An IP address for the first Ceph Monitor container.</li>
<li class="li">Login access to <code class="ph codeph">cp.icr.io/cp</code>.</li>
<li class="li">A minimum of 10 GB of free space.</li>
</ul>
</section>
<section class="section context">
<h2 class="sectiontitle">Procedure</h2>
<p>Bootstrap a storage cluster:</p>
<pre class="pre codeblock"><code>cephadm bootstrap --cluster-network 10.10.128.0/24 --mon-ip 10.10.128.68 --registry-url cp.icr.io/cp --registry-username cp --registry-password mypassword1 --yes-i-know</code></pre>
<p>The script takes a few minutes to complete.</p>
<pre class="pre codeblock"><code>Ceph Dashboard is now available at:
    URL: https://host01:8443/
    User: admin
    Password: i8nhu7zham</code></pre>
</section>
</div>
<nav class="related-links"><div class="familylinks">
<div class="parentlink"><strong>Parent:</strong> <a href="installation.html">Installing</a></div>
</div></nav>
</article></main></body></html>"""


def test_detect_component_from_topic():
    assert _detect_component_from_topic("installation-bootstrapping-new-storage-cluster") == "cephadm"
    assert _detect_component_from_topic("ceph-file-system-snapshots") == "cephfs"
    assert _detect_component_from_topic("object-gateway-multisite") == "radosgw"
    assert _detect_component_from_topic("block-device-mirroring") == "rbd"
    assert _detect_component_from_topic("stretch-mode-configuration") == "rados"
    assert _detect_component_from_topic("dashboard-overview") == "mgr"
    assert _detect_component_from_topic("overview") == "general"


def test_parse_ibm_page_produces_chunks():
    chunks = parse_ibm_page(
        html=SAMPLE_IBM_HTML,
        url="https://www.ibm.com/docs/en/storage-ceph/8.1.0?topic=installation-bootstrapping-new-storage-cluster",
        topic_slug="installation-bootstrapping-new-storage-cluster",
        version="8.1",
    )
    assert len(chunks) > 0
    assert chunks[0].component == "cephadm"
    assert chunks[0].version == "ibm-8.1"
    assert "ibm-docs/8.1/" in chunks[0].source_file
    assert "ibm.com" in chunks[0].doc_url


def test_parse_ibm_page_extracts_content():
    chunks = parse_ibm_page(
        html=SAMPLE_IBM_HTML,
        url="https://www.ibm.com/docs/en/storage-ceph/8.1.0?topic=installation-bootstrapping-new-storage-cluster",
        topic_slug="installation-bootstrapping-new-storage-cluster",
        version="8.1",
    )
    all_content = " ".join(c.content for c in chunks)
    assert "cephadm bootstrap" in all_content
    assert "cp.icr.io" in all_content
    assert "10 GB" in all_content


def test_parse_ibm_page_strips_navigation():
    chunks = parse_ibm_page(
        html=SAMPLE_IBM_HTML,
        url="https://www.ibm.com/docs/en/storage-ceph/8.1.0?topic=test",
        topic_slug="installation-bootstrapping-new-storage-cluster",
        version="8.1",
    )
    all_content = " ".join(c.content for c in chunks)
    assert "Parent:" not in all_content
    assert "familylinks" not in all_content


def test_parse_ibm_page_skips_thin_pages():
    thin_html = """<html><body><main><article>
    <h1>Overview</h1>
    <p>Short.</p>
    </article></main></body></html>"""
    chunks = parse_ibm_page(
        html=thin_html,
        url="https://example.com",
        topic_slug="overview",
        version="8.1",
    )
    assert len(chunks) == 0


def test_extract_code_examples():
    examples = extract_code_examples_from_page(
        html=SAMPLE_IBM_HTML,
        topic_slug="installation-bootstrapping-new-storage-cluster",
        version="8.1",
    )
    assert len(examples) >= 1
    assert any("cephadm bootstrap" in ex.code for ex in examples)
    assert examples[0].component == "cephadm"
    assert "ibm-docs/8.1/" in examples[0].source_file


def test_split_into_sections():
    content = """Introduction paragraph.

## Before you begin

Prerequisites here.

## Procedure

Steps here.

## Verification

Check results.
"""
    sections = _split_into_sections(content, "My Page")
    assert len(sections) == 4
    assert sections[0]["title"] == "My Page"
    assert sections[1]["title"] == "Before you begin"
    assert sections[2]["title"] == "Procedure"
    assert sections[3]["title"] == "Verification"
