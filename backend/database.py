import os
from typing import Any, Dict, Iterator, Mapping, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Charger les variables d'environnement
load_dotenv()

# Configuration de la base de données
DB_USER = os.getenv("DB_USER", "labondemand")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "labondemand")

# Valeurs par défaut du pool de connexions. pool_size + max_overflow (40)
# couvre le pool de threads d'AnyIO (40 threads) dans lequel FastAPI exécute
# les handlers synchrones : un pic de requêtes n'attend pas une connexion.
DEFAULT_POOL_SIZE = 10
DEFAULT_MAX_OVERFLOW = 30
DEFAULT_POOL_TIMEOUT = 30
# Recycler bien avant le wait_timeout de MariaDB (8 h par défaut) et les
# coupures silencieuses des équipements réseau intermédiaires.
DEFAULT_POOL_RECYCLE = 1800


def _env_int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    """Lit un entier ; une valeur invalide arrête le démarrage avec un message clair."""
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} doit être un entier (valeur reçue : {raw!r})") from None
    if value < minimum:
        raise ValueError(f"{name} doit être supérieur ou égal à {minimum} (valeur reçue : {value})")
    return value


def build_database_url(env: Optional[Mapping[str, str]] = None) -> URL:
    """Construit l'URL MariaDB/MySQL (PyMySQL) depuis les variables DB_*.

    ``URL.create`` échappe chaque composant : un mot de passe contenant ``@``,
    ``/``, ``:``, ``#``, ``%``… est transmis tel quel au pilote.
    """
    env = os.environ if env is None else env
    return URL.create(
        drivername="mysql+pymysql",
        username=env.get("DB_USER", "labondemand"),
        password=env.get("DB_PASSWORD", "password"),
        host=env.get("DB_HOST", "localhost"),
        port=_env_int(env, "DB_PORT", default=3306, minimum=1),
        database=env.get("DB_NAME", "labondemand"),
    )


def engine_options(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Options du moteur SQLAlchemy (pool) depuis les variables DB_POOL_*.

    - ``pool_pre_ping`` : teste la connexion avant usage et la remplace si le
      serveur l'a fermée (évite « MySQL server has gone away ») ;
    - ``pool_recycle`` : renouvelle les connexions plus anciennes que N
      secondes (``-1`` désactive le recyclage).
    """
    env = os.environ if env is None else env
    pool_recycle = _env_int(env, "DB_POOL_RECYCLE", DEFAULT_POOL_RECYCLE, minimum=-1)
    if pool_recycle == 0:
        raise ValueError("DB_POOL_RECYCLE doit valoir -1 (désactivé) ou un nombre de secondes > 0")
    return {
        "pool_size": _env_int(env, "DB_POOL_SIZE", DEFAULT_POOL_SIZE, minimum=1),
        "max_overflow": _env_int(env, "DB_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW, minimum=0),
        "pool_timeout": _env_int(env, "DB_POOL_TIMEOUT", DEFAULT_POOL_TIMEOUT, minimum=1),
        "pool_recycle": pool_recycle,
        "pool_pre_ping": True,
    }


# Construction de l'URL de connexion (str() masque le mot de passe)
SQLALCHEMY_DATABASE_URL = build_database_url()

# Options du moteur, exposées pour les tests et le diagnostic
ENGINE_OPTIONS = engine_options()

# Création du moteur de base de données (aucune connexion n'est ouverte ici)
engine = create_engine(SQLALCHEMY_DATABASE_URL, **ENGINE_OPTIONS)

# Création de la classe SessionLocal pour les instances de session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Classe de base pour les modèles ORM
Base = declarative_base()

# Fonction pour obtenir une session de base de données
def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
