# Seguridad de la plataforma

Documentación de seguridad del appliance ARGOS. Es la base del dossier para ENS categoría media e ISO/IEC 27001 (Fase 09, ADR-0014).

| Documento | Qué es | Estado |
|---|---|---|
| [Modelo de amenazas](modelo-amenazas.md) | Activos, adversarios, superficies y mitigaciones, cada una con su componente, su tarea y su evidencia | v1.0 (F09-01) |
| [Revisión de seguridad de F1–F8](revision-f01-f08.md) | 57 hallazgos tratados como los de un cliente, cada uno con su decisión y su tarea | v1.0 (F09-02) |
| Batería de accesos indebidos | Informe generado por la prueba contra la API desplegada | Pendiente (F09-15) |
| Dossier ENS / ISO 27001 | Medidas y controles con su estado y su evidencia | Pendiente (F09-16) |

`tests/docs/test_threat_model.py` comprueba el modelo en cada ejecución de los tests:
- toda mitigación cita su componente y tiene un estado válido;
- los diez componentes de la Fase 09 aparecen;
- todo adversario tiene al menos una mitigación;
- lo marcado `implementada` apunta a rutas que existen en el repositorio.
