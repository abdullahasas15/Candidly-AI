import os
import re
import math
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import pdfplumber
import docx

# Month mapping for timeline calculation
MONTH_MAP = {
    'jan': 0.0, 'january': 0.0,
    'feb': 1.0/12, 'february': 1.0/12,
    'mar': 2.0/12, 'march': 2.0/12,
    'apr': 3.0/12, 'april': 3.0/12,
    'may': 4.0/12,
    'jun': 5.0/12, 'june': 5.0/12,
    'jul': 6.0/12, 'july': 6.0/12,
    'aug': 7.0/12, 'august': 7.0/12,
    'sep': 8.0/12, 'september': 8.0/12, 'sept': 8.0/12,
    'oct': 9.0/12, 'october': 9.0/12,
    'nov': 10.0/12, 'november': 10.0/12,
    'dec': 11.0/12, 'december': 11.0/12
}

CATEGORIZED_SKILLS_TAXONOMY: Dict[str, List[str]] = {
    "Languages": [
        "Python", "JavaScript", "TypeScript", "Go", "Golang", "Java", "C++", "C#",
        "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "SQL", "Bash", "Shell",
        "HTML", "CSS", "R", "Dart", "Solidity"
    ],
    "Frameworks": [
        "React", "React.js", "Next.js", "Vue", "Vue.js", "Angular", "Node.js",
        "Express", "FastAPI", "Django", "Flask", "Spring Boot", "ASP.NET",
        "GraphQL", "REST API", "TailwindCSS", "Redux", "NestJS", "gRPC"
    ],
    "Databases": [
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Cassandra", "DynamoDB",
        "Elasticsearch", "Snowflake", "BigQuery", "SQLite", "Neo4j", "Oracle",
        "SQL Server", "Supabase", "Firebase", "Vector DB"
    ],
    "Cloud & DevOps": [
        "AWS", "Amazon Web Services", "GCP", "Google Cloud", "Azure", "Docker",
        "Kubernetes", "Terraform", "Helm", "CI/CD", "GitHub Actions", "GitLab CI",
        "Linux", "Nginx", "Ansible", "Prometheus", "Grafana", "ArgoCD"
    ],
    "Tools": [
        "Distributed Systems", "System Design", "Microservices", "Kafka", "RabbitMQ",
        "Git", "WebSockets", "Data Structures", "Algorithms", "Concurrency",
        "Multithreading", "Agile", "Scrum", "JIRA", "PyTorch", "TensorFlow", "LLMs"
    ]
}

ALL_TECH_SKILLS = [skill for cat in CATEGORIZED_SKILLS_TAXONOMY.values() for skill in cat]


def parse_date_to_float(date_str: str) -> Optional[float]:
    """Convert a date string like 'Jan 2020', '2019', '06/2021', 'Present' to a float year representation."""
    clean = date_str.strip().lower()
    now_year = datetime.utcnow().year + (datetime.utcnow().month - 1) / 12.0

    if clean in ['present', 'current', 'now', 'ongoing', 'today']:
        return round(now_year, 2)

    # Match Month Year (e.g. 'Jan 2021', 'September 2018')
    m_match = re.search(r'([a-z]{3,9})[\s,.\'\-]+(\d{4})', clean)
    if m_match:
        month_name = m_match.group(1)[:3]
        year = float(m_match.group(2))
        month_offset = MONTH_MAP.get(month_name, 0.0)
        return round(year + month_offset, 2)

    # Match MM/YYYY or MM-YYYY
    slash_match = re.search(r'(\d{1,2})[\/\-](\d{4})', clean)
    if slash_match:
        month = max(1, min(12, int(slash_match.group(1))))
        year = float(slash_match.group(2))
        return round(year + (month - 1) / 12.0, 2)

    # Match 4-digit year alone (e.g. '2020')
    year_match = re.search(r'(\d{4})', clean)
    if year_match:
        return float(year_match.group(1))

    return None


def merge_and_calculate_experience(intervals: List[Tuple[float, float]]) -> float:
    """Merges overlapping work experience intervals and calculates total non-overlapping years."""
    if not intervals:
        return 0.0

    valid_intervals = []
    for s, e in intervals:
        if s is not None and e is not None and s <= e:
            valid_intervals.append((s, e))

    if not valid_intervals:
        return 0.0

    valid_intervals.sort(key=lambda x: x[0])
    merged = [valid_intervals[0]]
    for current in valid_intervals[1:]:
        prev_start, prev_end = merged[-1]
        if current[0] <= prev_end:
            merged[-1] = (prev_start, max(prev_end, current[1]))
        else:
            merged.append(current)

    total_years = sum(e - s for s, e in merged)
    return round(max(0.0, total_years), 1)


import io

def extract_text_from_pdf(file_input: Any) -> Tuple[str, bool]:
    """
    Extracts text from PDF (file path or raw bytes).
    If extracted text is negligible (<60 characters), falls back to local Apple Vision OCR via ocrmac.
    Returns (extracted_text, ocr_used).
    """
    extracted_pages = []
    ocr_used = False

    try:
        pdf_source = io.BytesIO(file_input) if isinstance(file_input, (bytes, bytearray)) else file_input
        with pdfplumber.open(pdf_source) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True) or ""
                if text.strip():
                    extracted_pages.append(text)
    except Exception as e:
        print(f"pdfplumber extraction warning: {e}")

    full_text = "\n\n".join(extracted_pages).strip()

    # Check if text is sparse/scanned (< 60 chars)
    if len(full_text) < 60:
        try:
            import pypdfium2 as pdfium
            from ocrmac import ocrmac

            ocr_pages = []
            pdf_doc = pdfium.PdfDocument(file_input)
            for page_index in range(len(pdf_doc)):
                page = pdf_doc.get_page(page_index)
                pil_image = page.render(scale=2).to_pil()
                annotations = ocrmac.OCR(pil_image).recognize()
                page_lines = [ann[0] for ann in annotations if ann and ann[0].strip()]
                if page_lines:
                    ocr_pages.append("\n".join(page_lines))

            if ocr_pages:
                full_text = "\n\n".join(ocr_pages).strip()
                ocr_used = True
        except Exception as ocr_err:
            print(f"Local OCR fallback notice: {ocr_err}")

    return full_text, ocr_used


def extract_text_from_docx(file_input: Any) -> str:
    """Extracts text from DOCX (file path or raw bytes) while preserving paragraphs and table structures."""
    docx_source = io.BytesIO(file_input) if isinstance(file_input, (bytes, bytearray)) else file_input
    doc = docx.Document(docx_source)
    paragraphs = []
    for p in doc.paragraphs:
        if p.text.strip():
            paragraphs.append(p.text.strip())

    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                paragraphs.append(row_text)

    return "\n".join(paragraphs).strip()


def extract_text_from_file(file_input: Any, filename: Optional[str] = None) -> Tuple[str, str, bool]:
    """
    Extracts text from PDF, DOCX, or TXT.
    Accepts either (file_bytes: bytes, filename: str) or (file_path: str).
    Returns (extracted_text, file_type, ocr_used).
    """
    if isinstance(file_input, (bytes, bytearray)):
        name = filename or "resume.pdf"
        ext = os.path.splitext(name)[1].lower()
        if ext == '.pdf':
            text, ocr_used = extract_text_from_pdf(file_input)
            return text, 'pdf', ocr_used
        elif ext in ['.docx', '.doc']:
            text = extract_text_from_docx(file_input)
            return text, 'docx', False
        elif ext == '.txt':
            text = file_input.decode('utf-8', errors='replace')
            return text.strip(), 'txt', False
        else:
            raise ValueError(f"Unsupported resume format '{ext}'. Only PDF, DOCX, and TXT are supported.")
    else:
        file_path = str(file_input)
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.pdf':
            text, ocr_used = extract_text_from_pdf(file_path)
            return text, 'pdf', ocr_used
        elif ext in ['.docx', '.doc']:
            text = extract_text_from_docx(file_path)
            return text, 'docx', False
        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            return text.strip(), 'txt', False
        else:
            raise ValueError(f"Unsupported resume format '{ext}'. Only PDF, DOCX, and TXT are supported.")


# ---------------------------------------------------------------------------
# Section Segmenter & Multi-Section Extraction
# ---------------------------------------------------------------------------

SECTION_HEADERS = {
    "experience": [
        "work experience", "professional experience", "experience",
        "employment history", "work history", "career history"
    ],
    "education": [
        "education", "academic background", "academic history",
        "academics", "educational background", "degrees"
    ],
    "certifications": [
        "certifications", "certificates", "licenses & certifications",
        "professional certifications", "credentials", "accreditations"
    ],
    "projects": [
        "projects", "personal projects", "technical projects",
        "key projects", "notable projects", "open source"
    ],
    "skills": [
        "skills", "technical skills", "core competencies",
        "technologies", "tech stack", "tools & technologies"
    ],
    "summary": [
        "summary", "professional summary", "about me", "about",
        "profile", "executive summary", "objective"
    ]
}


def segment_resume_sections(text: str) -> Dict[str, List[str]]:
    """Segments resume text into logical sections based on common headings."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    sections: Dict[str, List[str]] = {k: [] for k in SECTION_HEADERS}
    sections["header"] = []

    current_section = "header"

    for line in lines:
        clean_lower = re.sub(r'[:#*_\-–—|]', '', line).strip().lower()
        matched_section = None

        if len(clean_lower) < 45:
            for sec_name, sec_keywords in SECTION_HEADERS.items():
                for kw in sec_keywords:
                    if clean_lower == kw or clean_lower.startswith(kw + " "):
                        matched_section = sec_name
                        break
                if matched_section:
                    break

        if matched_section:
            current_section = matched_section
        else:
            sections[current_section].append(line)

    return sections


def extract_contact_info(text: str) -> Dict[str, Optional[str]]:
    """Extracts email, phone, location, and social URLs."""
    info: Dict[str, Optional[str]] = {
        "name": None,
        "email": None,
        "phone": None,
        "location": None,
        "linkedin_url": None,
        "portfolio_url": None,
        "github_url": None
    }

    # Email
    email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', text)
    if email_match:
        info["email"] = email_match.group(1).lower()

    # Phone
    phone_match = re.search(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
    if phone_match:
        info["phone"] = phone_match.group(0).strip()

    # LinkedIn
    li_match = re.search(r'(https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+)', text, re.IGNORECASE)
    if li_match:
        info["linkedin_url"] = li_match.group(1)
    else:
        # Match "linkedin.com/in/..." without protocol
        li_sub = re.search(r'(?:linkedin\.com/in/([a-zA-Z0-9_-]+))', text, re.IGNORECASE)
        if li_sub:
            info["linkedin_url"] = f"https://linkedin.com/in/{li_sub.group(1)}"

    # GitHub
    gh_match = re.search(r'(https?://(?:www\.)?github\.com/[a-zA-Z0-9_-]+)', text, re.IGNORECASE)
    if gh_match:
        info["github_url"] = gh_match.group(1)
    else:
        gh_sub = re.search(r'(?:github\.com/([a-zA-Z0-9_-]+))', text, re.IGNORECASE)
        if gh_sub:
            info["github_url"] = f"https://github.com/{gh_sub.group(1)}"

    # Portfolio / personal website
    port_match = re.search(r'(https?://[a-zA-Z0-9_-]+\.(?:dev|io|me|app|site|tech|com)(?:/[^\s,]+)?)', text, re.IGNORECASE)
    if port_match:
        url = port_match.group(1)
        if 'linkedin.com' not in url and 'github.com' not in url:
            info["portfolio_url"] = url

    # Candidate Name (typically in top lines of header)
    # Candidate Name (typically in top lines of header)
    first_lines = [l.strip() for l in text.split('\n')[:4] if l.strip()]
    for l in first_lines:
        clean = re.sub(r'[^a-zA-Z\s\.\'-]', '', l).strip()
        words = clean.split()
        if 2 <= len(words) <= 4 and '@' not in l and not re.search(r'\b(resume|curriculum|vitae|developer|engineer)\b', clean, re.I):
            info["name"] = clean.title()
            break

    # Alias keys for consistency across services
    info["linkedin"] = info.get("linkedin_url")
    info["github"] = info.get("github_url")
    info["portfolio"] = info.get("portfolio_url")

    return info


def extract_schooling_education(education_lines: List[str], full_text: str) -> List[Dict[str, Any]]:
    """Extracts degree, institution, field of study, graduation year, GPA, and honors using contextual window analysis."""
    target_lines = education_lines if education_lines else [l.strip() for l in full_text.split('\n') if l.strip()]
    education_entries = []

    degree_patterns = [
        (r'\b(Ph\.?D\.?|Doctor(?:ate)?)\b', "Ph.D. / Doctorate"),
        (r'\b(Master(?:\'s)?\s+(?:of|in)?\s+[A-Za-z\s]+|M\.?S|M\.?Sc|M\.?Tech|M\.?Eng|M\.?B\.?A|M\.?C\.?A)\b', "Master's Degree"),
        (r'\b(Bachelor(?:\'s)?\s+(?:of|in)?\s+[A-Za-z\s]+|B\.?S|B\.?Sc|B\.?E|B\.?Tech|B\.?A|B\.?C\.?A)\b', "Bachelor's Degree"),
        (r'\b(Associate(?:\'s)?|Diploma)\b', "Associate Degree")
    ]

    for i, line in enumerate(target_lines):
        for pat, deg_name in degree_patterns:
            if re.search(pat, line, re.IGNORECASE):
                # Context window around the degree match
                start_w = max(0, i - 2)
                end_w = min(len(target_lines), i + 4)
                window_lines = target_lines[start_w:end_w]
                window_text = " \n ".join(window_lines)

                # Grad Year
                yr_match = re.search(r'\b(19\d{2}|20\d{2})\b', window_text)
                grad_year = int(yr_match.group(1)) if yr_match else None

                # GPA / CGPA
                gpa_match = re.search(r'(?:GPA|CGPA|Grade)[\s:]*([0-4]\.\d{1,2}(?:\s*/\s*4(?:\.0)?)?|[0-9]\.\d{1,2}(?:\s*/\s*10(?:\.0)?)?|\d{2,3}%)', window_text, re.IGNORECASE)
                gpa = gpa_match.group(1).strip() if gpa_match else None

                # Honors
                honors_match = re.search(r'\b(Cum Laude|Magna Cum Laude|Summa Cum Laude|Dean\'s List|Graduate Research Fellow|Honors|Distinction|First Class)\b[^\n]*', window_text, re.IGNORECASE)
                honors = honors_match.group(0).strip() if honors_match else None

                # Field of study
                field = "Computer Science"
                major_match = re.search(r'(?:in|of)\s+([a-zA-Z\s&]{4,45}?)(?:\n|\(|,|\.|$|with|from|\d{4})', line, re.IGNORECASE)
                if major_match and len(major_match.group(1).strip()) > 3:
                    field = major_match.group(1).strip().title()
                elif "electrical" in window_text.lower():
                    field = "Electrical Engineering and Computer Science"
                elif "information" in window_text.lower():
                    field = "Information Technology"

                # Institution
                inst = "University / College"
                for w in window_lines:
                    if any(token in w.lower() for token in ["university", "institute", "college", "school", "polytechnic", "academy"]):
                        # Extract the main university name before bullet points/locations
                        clean_inst = re.split(r'[•|–—\n]', w)[0].strip()
                        if len(clean_inst) > 3:
                            inst = clean_inst
                            break

                education_entries.append({
                    "degree": deg_name,
                    "institution": inst,
                    "field": field,
                    "graduation_year": grad_year,
                    "gpa": gpa,
                    "honors": honors
                })
                break

    # Deduplicate by degree title
    deduped = []
    seen = set()
    for e in education_entries:
        if e["degree"] not in seen:
            seen.add(e["degree"])
            deduped.append(e)

    return deduped


def extract_certifications(cert_lines: List[str], full_text: str) -> List[Dict[str, Any]]:
    """Extracts industry certifications, issuing bodies, years, and credential IDs."""
    target_lines = cert_lines if cert_lines else [l.strip() for l in full_text.split('\n') if l.strip()]
    certifications = []

    cert_patterns = [
        (r'AWS\s+Certified\s+([A-Za-z\s]+)', "Amazon Web Services"),
        (r'Google\s+Cloud\s+Certified\s+([A-Za-z\s]+)', "Google Cloud"),
        (r'Microsoft\s+Certified[:\s]+([A-Za-z0-9\s]+)', "Microsoft Azure"),
        (r'(CKA|Certified\s+Kubernetes\s+Administrator)', "Cloud Native Computing Foundation (CNCF)"),
        (r'(CKAD|Certified\s+Kubernetes\s+Application\s+Developer)', "Cloud Native Computing Foundation (CNCF)"),
        (r'HashiCorp\s+Certified[:\s]+([A-Za-z0-9\s]+)', "HashiCorp"),
        (r'(CISSP|Certified\s+Information\s+Systems\s+Security\s+Professional)', "(ISC)²"),
        (r'(CompTIA\s+[A-Za-z+]+)', "CompTIA"),
        (r'(PMP|Project\s+Management\s+Professional)', "PMI"),
        (r'(Certified\s+Scrum\s+Master|CSM)', "Scrum Alliance")
    ]

    for line in target_lines:
        line_clean = line.strip()
        matched = False
        for pat, issuer in cert_patterns:
            m = re.search(pat, line_clean, re.IGNORECASE)
            if m:
                cert_name = line_clean.split('|')[0].split('(')[0].strip()
                # Clean leading dashes or bullets
                cert_name = re.sub(r'^[\s•\-*]+', '', cert_name).strip()

                # Year
                yr_match = re.search(r'\b(20\d{2}|19\d{2})\b', line_clean)
                yr = int(yr_match.group(1)) if yr_match else None

                # Credential ID
                cred_match = re.search(r'(?:Credential ID|ID|License)[:\s]*([A-Za-z0-9\-_]+)', line_clean, re.IGNORECASE)
                cred_id = cred_match.group(1) if cred_match else None

                certifications.append({
                    "name": cert_name,
                    "issuing_org": issuer,
                    "issue_year": yr,
                    "credential_id": cred_id,
                    "url": None
                })
                matched = True
                break

        # Fallback for explicit lines in certification section
        if not matched and cert_lines and len(line_clean) > 5 and len(line_clean) < 100:
            if any(w in line_clean.lower() for w in ["certified", "certificate", "certification", "foundation", "practitioner", "architect", "engineer"]):
                yr_match = re.search(r'\b(20\d{2})\b', line_clean)
                clean_name = re.sub(r'^[\s•\-*]+', '', line_clean).strip()
                certifications.append({
                    "name": clean_name,
                    "issuing_org": "Accredited Body",
                    "issue_year": int(yr_match.group(1)) if yr_match else None,
                    "credential_id": None,
                    "url": None
                })

    # Deduplicate
    seen_certs = set()
    deduped = []
    for c in certifications:
        key = c["name"].lower()
        if key not in seen_certs:
            seen_certs.add(key)
            deduped.append(c)
    return deduped


def extract_projects(project_lines: List[str], full_text: str) -> List[Dict[str, Any]]:
    """Extracts project name, role, tech stack, summary, and links."""
    projects = []
    lines = project_lines if project_lines else []

    if not lines:
        for line in full_text.split('\n'):
            if re.match(r'^(?:Project|Key Project)[:\s]+', line, re.I):
                lines.append(line)

    current_project = None
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        url_match = re.search(r'(https?://[^\s]+|github\.com/[^\s]+)', line_clean, re.I)

        # Check for role line
        if re.match(r'^Role[:\s]+', line_clean, re.I):
            if current_project:
                current_project["role"] = re.sub(r'^Role[:\s]+', '', line_clean, flags=re.I).strip()
            continue

        # Check for technologies line
        if re.match(r'^(?:Technologies|Tech Stack|Tools)[:\s]+', line_clean, re.I):
            if current_project:
                tech_str = re.sub(r'^(?:Technologies|Tech Stack|Tools)[:\s]+', '', line_clean, flags=re.I)
                extracted_techs = [t.strip() for t in re.split(r'[,;•|]', tech_str) if t.strip()]
                for t in extracted_techs:
                    if t not in current_project["technologies"]:
                        current_project["technologies"].append(t)
            continue

        # Check for repository/URL line
        if re.match(r'^(?:Repository|Repo|Link|URL|Demo)[:\s]+', line_clean, re.I):
            if current_project and url_match:
                current_project["url"] = url_match.group(1)
            continue

        # Determine if this line is a new project title
        is_header = False
        if '|' in line_clean or ' - ' in line_clean or line_clean.startswith(('Project:', 'Key Project:')):
            is_header = True
        elif len(line_clean) < 80 and not line_clean.startswith(('•', '-', '*', 'http')) and any(k in line_clean.lower() for k in ['system', 'app', 'service', 'engine', 'platform', 'tool', 'bot', 'store', 'ai', 'store']):
            is_header = True

        if is_header and not line_clean.lower().startswith(('role:', 'technologies:', 'tech:', 'repository:')):
            if current_project:
                projects.append(current_project)

            parts = [p.strip() for p in re.split(r'[|•–—]', line_clean) if p.strip()]
            title = parts[0] if parts else line_clean
            title = re.sub(r'^(?:Project|Key Project)[:\s]+', '', title, flags=re.I).strip()

            techs = []
            for t in ALL_TECH_SKILLS:
                if re.search(r'\b' + re.escape(t.lower()) + r'\b', line_clean.lower()):
                    techs.append(t)

            current_project = {
                "title": title,
                "role": "Creator / Core Engineer",
                "technologies": techs,
                "description": line_clean,
                "url": url_match.group(1) if url_match else None
            }
        elif current_project:
            current_project["description"] += " " + line_clean
            for t in ALL_TECH_SKILLS:
                if t not in current_project["technologies"] and re.search(r'\b' + re.escape(t.lower()) + r'\b', line_clean.lower()):
                    current_project["technologies"].append(t)
            if not current_project["url"] and url_match:
                current_project["url"] = url_match.group(1)

    if current_project:
        projects.append(current_project)

    return projects[:6]


def extract_categorized_skills(text: str) -> Tuple[List[str], Dict[str, List[str]]]:
    """Matches text against taxonomy and organizes skills into 5 distinct categories."""
    text_lower = text.lower()
    detected_all = []
    categorized: Dict[str, List[str]] = {k: [] for k in CATEGORIZED_SKILLS_TAXONOMY}

    for cat_name, skill_list in CATEGORIZED_SKILLS_TAXONOMY.items():
        for skill in skill_list:
            pattern = r'\b' + re.escape(skill.lower()) + r'\b'
            if re.search(pattern, text_lower):
                if skill not in detected_all:
                    detected_all.append(skill)
                if skill not in categorized[cat_name]:
                    categorized[cat_name].append(skill)

    return detected_all, categorized


def parse_structured_resume_data(text: str) -> Dict[str, Any]:
    """
    Parses full extracted resume text into rich, complete structured components:
    - summary: candidate professional summary / objective
    - work_experience: list of {company, role, start_date, end_date, duration_years, description, highlights, technologies}
    - education: list of {degree, institution, field, graduation_year, gpa, honors}
    - certifications: list of {name, issuing_org, issue_year, credential_id, url}
    - projects: list of {title, role, technologies, description, url}
    - skills: list of all detected skills
    - skills_by_category: {languages, frameworks, databases, cloud_devops, tools_architecture}
    - contact_info: {name, email, phone, location, linkedin_url, github_url, portfolio_url}
    - total_experience_years: float computed from non-overlapping intervals
    """
    sections = segment_resume_sections(text)
    contact_info = extract_contact_info(text)

    # 1. Summary
    summary = " ".join(sections.get("summary", []))[:600].strip()
    if not summary:
        # Fallback to header snippet if it contains descriptive sentences
        for line in sections.get("header", []):
            if len(line) > 60 and '@' not in line:
                summary = line[:500]
                break

    # 2. Work Experience
    work_lines = sections.get("experience", [])
    if not work_lines:
        work_lines = [l.strip() for l in text.split('\n') if l.strip()]

    work_experience = []
    intervals = []

    date_range_regex = re.compile(
        r'([a-zA-Z]{3,9}\s+\d{4}|\d{4}|\d{1,2}\/\d{4})\s*(?:[-–—to]+|\s+to\s+)\s*([a-zA-Z]{3,9}\s+\d{4}|\d{4}|\d{1,2}\/\d{4}|Present|Current|Now)',
        re.IGNORECASE
    )

    for i, line in enumerate(work_lines):
        match = date_range_regex.search(line)
        if match:
            start_str = match.group(1).strip()
            end_str = match.group(2).strip()

            start_float = parse_date_to_float(start_str)
            end_float = parse_date_to_float(end_str)

            if start_float and end_float and end_float >= start_float:
                duration_years = round(end_float - start_float, 1)
                intervals.append((start_float, end_float))

                text_without_date = line[:match.start()] + " " + line[match.end():]
                text_without_date = re.sub(r'[\(\)\[\]\|•\-,:]', ' ', text_without_date).strip()
                parts = [p.strip() for p in re.split(r'\s{2,}|\bat\b|\bfor\b|\b\|\b', text_without_date, flags=re.IGNORECASE) if p.strip()]

                role = parts[0] if len(parts) > 0 else "Software Engineer"
                company = parts[1] if len(parts) > 1 else (work_lines[i-1] if i > 0 and len(work_lines[i-1]) < 60 else "Company")

                # Contextual bullet points / highlights from subsequent lines
                desc_snippets = []
                highlights = []
                tech_used = []

                for j in range(i+1, min(len(work_lines), i+6)):
                    sub_line = work_lines[j]
                    if not date_range_regex.search(sub_line) and len(sub_line) > 8:
                        desc_snippets.append(sub_line)
                        if sub_line.startswith(('•', '-', '*', '–')):
                            highlights.append(sub_line.lstrip('•-*– ').strip())
                        for t in ALL_TECH_SKILLS:
                            if t not in tech_used and re.search(r'\b' + re.escape(t.lower()) + r'\b', sub_line.lower()):
                                tech_used.append(t)
                    else:
                        break

                work_experience.append({
                    "company": company,
                    "role": role,
                    "start_date": start_str,
                    "end_date": end_str,
                    "duration_years": duration_years,
                    "description": " ".join(desc_snippets)[:350] if desc_snippets else line,
                    "highlights": highlights[:5],
                    "technologies": tech_used
                })

    # If regex above found no distinct entries, fallback heuristic
    if not work_experience:
        simple_year_regex = re.compile(r'(\d{4})\s*[-–—to]+\s*(\d{4}|Present|Current|Now)', re.IGNORECASE)
        for i, line in enumerate(work_lines):
            match = simple_year_regex.search(line)
            if match:
                s_str, e_str = match.group(1), match.group(2)
                s_f = parse_date_to_float(s_str)
                e_f = parse_date_to_float(e_str)
                if s_f and e_f and e_f >= s_f:
                    intervals.append((s_f, e_f))
                    work_experience.append({
                        "company": "Professional Experience",
                        "role": line[:match.start()].strip() or "Engineer",
                        "start_date": s_str,
                        "end_date": e_str,
                        "duration_years": round(e_f - s_f, 1),
                        "description": line,
                        "highlights": [],
                        "technologies": []
                    })

    total_experience_years = merge_and_calculate_experience(intervals)

    if total_experience_years == 0.0:
        exp_stated_match = re.search(r'(\d+(?:\.\d+)?)\+?\s*years(?:\s+of)?\s+experience', text, re.IGNORECASE)
        if exp_stated_match:
            total_experience_years = float(exp_stated_match.group(1))

    # 3. Schooling / Education
    education = extract_schooling_education(sections.get("education", []), text)

    # 4. Certifications
    certifications = extract_certifications(sections.get("certifications", []), text)

    # 5. Projects
    projects = extract_projects(sections.get("projects", []), text)

    # 6. Categorized Skills
    skills_all, skills_by_category = extract_categorized_skills(text)

    return {
        "summary": summary,
        "work_experience": work_experience,
        "education": education,
        "certifications": certifications,
        "projects": projects,
        "skills": skills_all,
        "skills_by_category": skills_by_category,
        "contact_info": contact_info,
        "total_experience_years": round(total_experience_years, 1)
    }


def detect_discrepancies(
    self_reported_years: float,
    structured_data: Dict[str, Any],
    job: Any = None
) -> List[Dict[str, Any]]:
    """
    Compares candidate's self-reported claims against resume-derived data.
    Generates actionable discrepancy flags if significant divergence exists.
    """
    flags = []
    resume_years = float(structured_data.get("total_experience_years", 0.0))

    # 1. Experience Years Discrepancy Check (Threshold: > 1.0 year divergence)
    diff = self_reported_years - resume_years
    if abs(diff) > 1.0:
        if diff > 0:
            reason = (
                f"Candidate stated {self_reported_years:.1f} years of professional experience, "
                f"but verified resume timeline totals approximately {resume_years:.1f} years "
                f"({diff:.1f} years gap between claim and timeline dates)."
            )
        else:
            reason = (
                f"Candidate stated {self_reported_years:.1f} years of experience, "
                f"while resume timeline totals approximately {resume_years:.1f} years."
            )

        flags.append({
            "field_name": "years_of_experience",
            "candidate_stated_value": f"{self_reported_years:.1f} Years",
            "resume_derived_value": f"{resume_years:.1f} Years",
            "flag_reason": reason,
            "reviewed_by_recruiter": False
        })

    # 2. Education Degree Discrepancy Check
    if job and hasattr(job, 'min_degree_level') and job.min_degree_level:
        min_deg = job.min_degree_level.lower()
        resume_degrees = [e.get("degree", "").lower() for e in structured_data.get("education", [])]

        if "master" in min_deg:
            has_master = any("master" in d or "ph.d" in d for d in resume_degrees)
            if not has_master and resume_degrees:
                flags.append({
                    "field_name": "min_degree_level",
                    "candidate_stated_value": "Meets Degree Requirement",
                    "resume_derived_value": ", ".join([e.get("degree", "") for e in structured_data.get("education", [])]),
                    "flag_reason": f"Role specifies '{job.min_degree_level}', but resume records show: {', '.join(resume_degrees).title()}.",
                    "reviewed_by_recruiter": False
                })

    return flags
