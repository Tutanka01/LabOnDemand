"""
Délais par défaut des appels REST Kubernetes.

Le client Python Kubernetes n'applique aucun délai lorsque l'appelant ne
fournit pas ``_request_timeout`` : un apiserver lent ou injoignable bloque
alors indéfiniment le thread appelant (et, par ricochet, le pool de threads
de l'API). Ce module enveloppe ``RESTClientObject.request`` — point de
passage unique de tous les appels REST — pour appliquer un couple
``(connexion, lecture)`` par défaut.

Règles :
  - un ``_request_timeout`` explicite (non ``None``) de l'appelant est conservé
    tel quel ; ``(None, None)`` permet donc de désactiver le délai ;
  - les appels en flux (``_preload_content=False`` : watch, suivi de logs)
    ne reçoivent que le délai de connexion, jamais de délai de lecture court ;
  - une valeur ``<= 0`` désactive la composante correspondante.

Le chemin websocket (``kubernetes.stream.stream`` : exec, terminal, fichiers)
remplace temporairement ``ApiClient.request`` et ne passe jamais par
``RESTClientObject`` : il n'est pas concerné.
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable, Optional, Tuple, Union

from kubernetes.client import rest

logger = logging.getLogger("labondemand.k8s")

RequestTimeout = Union[None, int, float, Tuple[Optional[float], Optional[float]]]

# Attribut posé sur l'enveloppe pour rendre l'installation idempotente.
_WRAPPED_MARKER = "__labondemand_default_timeout__"


def _positive_or_none(value: Optional[float]) -> Optional[float]:
    """Retourne la valeur si elle est strictement positive, sinon None."""
    if value is None:
        return None
    return value if value > 0 else None


def resolve_request_timeout(
    explicit: RequestTimeout,
    preload_content: bool,
    connect: Optional[float],
    read: Optional[float],
) -> RequestTimeout:
    """Calcule le ``_request_timeout`` effectif d'un appel REST.

    ``explicit`` est la valeur fournie par l'appelant (``None`` si absente) ;
    ``connect`` / ``read`` sont les délais par défaut configurés.
    """
    if explicit is not None:
        return explicit
    connect_timeout = _positive_or_none(connect)
    # Flux longs (watch, logs suivis) : pas de délai de lecture par défaut.
    read_timeout = _positive_or_none(read) if preload_content else None
    if connect_timeout is None and read_timeout is None:
        return None
    return (connect_timeout, read_timeout)


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Retire une éventuelle enveloppe posée par une installation précédente."""
    while getattr(func, _WRAPPED_MARKER, False):
        func = func.__wrapped__  # type: ignore[attr-defined]
    return func


def install_default_request_timeout(
    connect: Optional[float], read: Optional[float]
) -> bool:
    """Installe (ou réinstalle) les délais par défaut sur ``RESTClientObject``.

    Idempotent : un nouvel appel remplace les valeurs précédentes sans
    empiler d'enveloppes. Retourne False si la signature du client ne
    permet pas l'installation (le client reste alors inchangé).
    """
    original = _unwrap(rest.RESTClientObject.request)
    try:
        signature = inspect.signature(original)
    except (TypeError, ValueError):
        logger.warning(
            "k8s_default_timeout_not_installed",
            extra={"extra_fields": {"reason": "signature_unavailable"}},
        )
        return False

    parameters = signature.parameters
    if "_request_timeout" not in parameters:
        logger.warning(
            "k8s_default_timeout_not_installed",
            extra={"extra_fields": {"reason": "missing_request_timeout_param"}},
        )
        return False

    preload_param = parameters.get("_preload_content")
    preload_default = (
        preload_param.default
        if preload_param is not None
        and preload_param.default is not inspect.Parameter.empty
        else True
    )

    @functools.wraps(original)
    def request_with_default_timeout(*args: Any, **kwargs: Any) -> Any:
        try:
            bound = signature.bind(*args, **kwargs)
        except TypeError:
            # Signature inattendue : on laisse le client lever sa propre erreur.
            return original(*args, **kwargs)
        arguments = bound.arguments
        explicit = arguments.get("_request_timeout")
        if explicit is None:
            preload = arguments.get("_preload_content", preload_default)
            arguments["_request_timeout"] = resolve_request_timeout(
                None, bool(preload), connect, read
            )
        return original(*bound.args, **bound.kwargs)

    setattr(request_with_default_timeout, _WRAPPED_MARKER, True)
    rest.RESTClientObject.request = request_with_default_timeout  # type: ignore[method-assign]
    logger.info(
        "k8s_default_timeout_installed",
        extra={
            "extra_fields": {
                "connect_timeout": _positive_or_none(connect),
                "read_timeout": _positive_or_none(read),
            }
        },
    )
    return True


def uninstall_default_request_timeout() -> None:
    """Restaure la méthode d'origine (utile pour les tests)."""
    rest.RESTClientObject.request = _unwrap(rest.RESTClientObject.request)  # type: ignore[method-assign]
