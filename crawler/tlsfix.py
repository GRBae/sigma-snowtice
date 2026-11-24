"""
중간 인증서를 안 보내는 서버 대응 (AIA chasing).

일부 학과 서버는 TLS 연결 때 중간 인증서를 빼먹는다. 브라우저는 인증서 안의 AIA 주소(CA Issuers)에서
중간 인증서를 내려받아 체인을 완성하지만, Python requests는 그러지 않아 SSLError가 난다.
여기서 브라우저와 똑같이 중간 인증서를 받아 '공식 루트(certifi) + 중간 인증서' 묶음을 만들고,
그 묶음으로 **검증을 켠 채** 다시 접속한다. 검증을 끄지 않는다.
"""
from __future__ import annotations

import ssl
import tempfile
import urllib.request

import certifi
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

_cache: dict[str, str] = {}


def _issuer_url(cert: x509.Certificate) -> str | None:
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return None
    for d in aia:
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
            return d.access_location.value
    return None


def _load(data: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(data) if b"BEGIN CERTIFICATE" in data else x509.load_der_x509_certificate(data)


def bundle_for(host: str, port: int = 443) -> str:
    """host용 CA 묶음 파일 경로. 서버 인증서의 AIA를 따라 중간 인증서를 최대 3단계 받는다."""
    if host in _cache:
        return _cache[host]
    # 서버가 보낸 인증서 한 장(검증 전)은 'AIA 주소를 읽는 용도'로만 쓴다. 실제 접속은 아래 묶음으로 검증한다.
    cert = x509.load_pem_x509_certificate(ssl.get_server_certificate((host, port)).encode())
    extra: list[bytes] = []
    for _ in range(3):
        url = _issuer_url(cert)
        if not url or cert.issuer == cert.subject:
            break
        with urllib.request.urlopen(url, timeout=15) as r:
            cert = _load(r.read())
        extra.append(cert.public_bytes(Encoding.PEM))
    if not extra:
        raise RuntimeError(f"{host}: 중간 인증서 주소(AIA)를 찾지 못함")
    f = tempfile.NamedTemporaryFile("wb", suffix=f"-{host}.pem", delete=False)
    f.write(open(certifi.where(), "rb").read() + b"\n" + b"".join(extra))
    f.close()
    _cache[host] = f.name
    return f.name
