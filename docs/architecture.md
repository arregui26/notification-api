# Decisiones de arquitectura

1. **API y worker separados.** Aceptar una solicitud depende de la transacción local, no del
   tiempo de respuesta de Telegram. No se usan tareas en memoria que desaparecen al reiniciar.
2. **PostgreSQL como cola pequeña.** Evita añadir Redis o un broker para este alcance. El índice
   de disponibilidad y el bloqueo de fila permiten consumidores concurrentes. Una transacción
   se mantiene durante la llamada de red: es simple y verificable, pero limita el rendimiento
   y retiene una conexión. Una carga mayor requeriría leases, un broker y más observabilidad.
3. **Clave única y huella del contenido.** La base arbitra carreras entre solicitudes. La misma
   clave con otro contenido produce conflicto; no se convierte en un envío nuevo.
4. **Destinos nombrados.** Un cliente autenticado solo puede seleccionar alias existentes. Los
   IDs de chat pertenecen a la configuración del servidor, no a la petición ni a su respuesta.
5. **Modo mock por defecto.** Facilita clonar y evaluar el proyecto sin credenciales ni efectos
   externos. El modo queda guardado en cada trabajo para impedir cambios de proveedor silenciosos.
6. **Errores públicos estables.** Se guardan códigos propios y no excepciones del proveedor que
   podrían contener el token en una URL. No se persiste la respuesta cruda de Telegram.
7. **Pruebas PostgreSQL reales.** SQLite sirve para reglas HTTP y de reintentos; no valida
   `SKIP LOCKED`. La exclusión entre workers se comprueba contra PostgreSQL.
8. **Alcance deliberado.** Una instalación y una clave API. Sin usuarios, tenants, administración
   visual, canales extra ni promesas de entrega exactamente una vez.

## Próximas mejoras posibles

- Retención programada y un registro separado de claves de idempotencia.
- Métricas de cola y alertas para trabajos fallidos.
- Autenticación por cliente y límites de tráfico independientes.
- Un segundo adaptador de entrega, manteniendo el contrato de la API.

## Referencias

- https://www.postgresql.org/docs/current/sql-select.html
- https://fastapi.tiangolo.com/advanced/testing-events/
- https://core.telegram.org/bots/api#sendmessage
