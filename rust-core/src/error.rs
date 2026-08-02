use std::fmt;

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum EngineError {
    RuntimeBuild(String),
    SchedulerPanicked,
    SchedulerIncomplete {
        spawned: usize,
        completed: usize,
        expected: usize,
    },
    TaskJoin(String),
    ResultChannelClosed,
    WriterPanicked,
    Output(String),
    Incomplete {
        emitted: usize,
        expected: usize,
    },
}

impl EngineError {
    pub(crate) fn is_output_failure(&self) -> bool {
        matches!(self, Self::WriterPanicked | Self::Output(_))
    }

    pub(crate) fn is_incomplete_stream(&self) -> bool {
        matches!(self, Self::Incomplete { .. })
    }
}

impl fmt::Display for EngineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RuntimeBuild(detail) => {
                write!(
                    formatter,
                    "No se pudo iniciar el runtime Rust asíncrono: {detail}"
                )
            }
            Self::SchedulerPanicked => {
                formatter.write_str("Error interno en el scheduler Rust asíncrono")
            }
            Self::SchedulerIncomplete {
                spawned,
                completed,
                expected,
            } => {
                write!(
                    formatter,
                    "Scheduler incompleto: {spawned} tareas creadas, \
                     {completed} completadas, {expected} esperadas"
                )
            }
            Self::TaskJoin(detail) => {
                write!(
                    formatter,
                    "Error interno en una tarea de escaneo Rust: {detail}"
                )
            }
            Self::ResultChannelClosed => {
                formatter.write_str("Canal de resultados Rust cerrado inesperadamente")
            }
            Self::WriterPanicked => formatter.write_str("Error interno en el hilo de salida Rust"),
            Self::Output(detail) => formatter.write_str(detail),
            Self::Incomplete { emitted, expected } => {
                write!(
                    formatter,
                    "Streaming incompleto: {emitted} de {expected} resultados"
                )
            }
        }
    }
}

impl std::error::Error for EngineError {}

#[cfg(test)]
mod tests {
    use super::EngineError;

    #[test]
    fn incomplete_error_preserves_existing_diagnostic() {
        let error = EngineError::Incomplete {
            emitted: 3,
            expected: 5,
        };
        assert_eq!(error.to_string(), "Streaming incompleto: 3 de 5 resultados");
        assert!(error.is_incomplete_stream());
        assert!(!error.is_output_failure());
    }

    #[test]
    fn output_failures_are_classified_for_error_precedence() {
        assert!(EngineError::WriterPanicked.is_output_failure());
        assert!(EngineError::Output("fallo".to_string()).is_output_failure());
        assert!(!EngineError::ResultChannelClosed.is_output_failure());
    }
}
