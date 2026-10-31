"""Trimmed-down copies of real upstream responses, used to mock HTTP in tests."""

ESEARCH_JSON = {"esearchresult": {"count": "2", "retmax": "2", "idlist": ["222", "111"]}}

EFETCH_XML = """<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN"
  "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">111</PMID>
      <Article>
        <Journal><Title>Journal of Medicinal Chemistry</Title>
          <JournalIssue><PubDate><Year>2019</Year><Month>Nov</Month></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Unrelated <i>title</i> about bananas</ArticleTitle>
        <Abstract><AbstractText>Bananas are yellow.</AbstractText></Abstract>
        <AuthorList><Author><LastName>Doe</LastName><Initials>J</Initials></Author></AuthorList>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">111</ArticleId>
      <ArticleId IdType="doi">10.1000/bananas</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">222</PMID>
      <Article>
        <Journal><Title>Nature</Title>
          <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>KRAS G12C covalent inhibitor docking study</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">KRAS G12C covalent inhibitor design.</AbstractText>
          <AbstractText Label="RESULTS">Docking ranks covalent inhibitors well.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Smith</LastName><ForeName>Anna</ForeName><Initials>A</Initials></Author>
          <Author><CollectiveName>KRAS Consortium</CollectiveName></Author>
        </AuthorList>
        <ArticleDate DateType="Electronic"><Year>2021</Year><Month>03</Month><Day>7</Day></ArticleDate>
      </Article>
      <MeshHeadingList><MeshHeading><DescriptorName>Proto-Oncogene Proteins p21(ras)</DescriptorName></MeshHeading></MeshHeadingList>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">222</ArticleId>
      <ArticleId IdType="doi">10.1000/kras</ArticleId>
      <ArticleId IdType="pmc">PMC999</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

EUROPEPMC_BIORXIV_JSON = {
    "hitCount": 57,
    "resultList": {
        "result": [
            {
                "id": "PPR100",
                "source": "PPR",
                "doi": "10.1101/2024.01.01.000001",
                "title": "KRAS G12C <i>covalent</i> inhibitor docking",
                "authorString": "Lee A, Kim B.",
                "authorList": {"author": [{"fullName": "Lee A"}, {"fullName": "Kim B"}]},
                "abstractText": "<h4>Abstract</h4> We dock KRAS G12C covalent inhibitors &amp; more.",
                "firstPublicationDate": "2024-01-02",
                "inEPMC": "Y",
                "bookOrReportDetails": {"publisher": "bioRxiv", "edition": "2"},
            },
            {
                "id": "PPR200",
                "source": "PPR",
                "doi": "10.1101/2024.02.02.000002",
                "title": "Something else entirely",
                "authorString": "Roe C.",
                "abstractText": None,
                "firstPublicationDate": "2024-02-02",
                "inEPMC": "N",
            },
        ]
    },
}

CROSSREF_CHEMRXIV_JSON = {
    "message": {
        "total-results": 3,
        "items": [
            {
                "DOI": "10.26434/chemrxiv-2023-abcde",
                "title": ["Covalent KRAS inhibitors: a docking benchmark"],
                "abstract": "<jats:p>We benchmark docking of KRAS G12C covalent inhibitors.</jats:p>",
                "posted": {"date-parts": [[2023, 9, 12]]},
                "author": [{"given": "Renne", "family": "Leini"}],
                "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
            },
            {
                "DOI": "10.26434/chemrxiv-2023-abcde-v2",
                "title": ["Covalent KRAS inhibitors: a docking benchmark (v2)"],
                "abstract": "<jats:p>Updated version.</jats:p>",
                "posted": {"date-parts": [[2025, 3, 27]]},
                "author": [{"given": "Renne", "family": "Leini"}],
            },
            {
                "DOI": "10.26434/chemrxiv.9757583.v1",
                "title": ["Solvent effects in Diels-Alder reactions"],
                "posted": {"date-parts": [[2019, 9, 1]]},
                "author": [{"name": "Chem Group"}],
            },
        ],
    }
}

LENS_SEARCH_JSON = {
    "total": 1234,
    "max_score": 16.9,
    "results": 1,
    "data": [
        {
            "lens_id": "031-156-664-516-153",
            "jurisdiction": "US",
            "doc_number": "11000000",
            "kind": "B2",
            "date_published": "2021-05-11",
            "publication_type": "GRANTED_PATENT",
            "biblio": {
                "invention_title": [
                    {"text": "Inhibiteurs covalents de KRAS", "lang": "fr"},
                    {"text": "Covalent KRAS G12C inhibitors", "lang": "en"},
                ],
                "parties": {
                    "applicants": [{"extracted_name": {"value": "ACME PHARMA INC"}}],
                    "inventors": [
                        {"extracted_name": {"value": "OCHOA JORGE"}},
                        {"extracted_name": {"value": "SMITH ANNA"}},
                    ],
                },
            },
            "abstract": [{"text": "Compounds that covalently inhibit KRAS G12C.", "lang": "en"}],
        }
    ],
}

LENS_FULL_RECORD_JSON = {
    "total": 1,
    "data": [
        {
            **LENS_SEARCH_JSON["data"][0],
            "claims": [
                {
                    "lang": "en",
                    "claims": [
                        {"claim_text": ["A compound of formula (I)."]},
                        {"claim_text": ["The compound of claim 1, wherein R is methyl."]},
                    ],
                }
            ],
            "description": {"text": "Field of the invention. KRAS is a GTPase.", "lang": "en"},
        }
    ],
}

JATS_XML = """<?xml version="1.0"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.2 20190208//EN" "JATS-archivearticle1.dtd">
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <title-group><article-title>Docking KRAS G12C</article-title></title-group>
    <abstract><p>Short abstract.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Introduction</title>
      <p>KRAS is an oncogene <xref ref-type="bibr" rid="r1">[1]</xref>.</p>
      <sec><title>Background</title><p>Covalent inhibitors target C12.</p></sec>
    </sec>
    <sec><title>Methods</title>
      <p>We used AutoDock Vina.</p>
      <fig id="f1"><caption><p>Docking poses.</p></caption></fig>
      <disp-formula>E = mc^2</disp-formula>
    </sec>
  </body>
  <back><ref-list><ref id="r1"><mixed-citation>Ref one.</mixed-citation></ref></ref-list></back>
</article>
"""
