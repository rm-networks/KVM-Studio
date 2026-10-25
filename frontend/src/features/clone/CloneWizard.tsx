import { CircleCheck, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type LibraryInfo, type TaskInfo, type VmSummary } from "../../api/client";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Wizard } from "../../components/Wizard";
import { isValidName } from "../library/names";
import { uniqueName } from "../wizard/defaults";
import "./CloneWizard.css";

const STEPS = ["source", "kind", "name", "folder", "summary", "copy"] as const;
type Step = (typeof STEPS)[number];
type Kind = "full" | "linked";

// How often the copy is followed.
const POLL_MS = 400;

interface Props {
  source: VmSummary;
  onClose: () => void;
}

export function CloneWizard({ source, onClose }: Props) {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>("source");
  const [kind, setKind] = useState<Kind>("full");
  const [name, setName] = useState("");
  const [folder, setFolder] = useState(source.folder);
  const [library, setLibrary] = useState<LibraryInfo | null>(null);
  const [taken, setTaken] = useState<ReadonlySet<string>>(new Set());
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.library(), api.listVms()])
      .then(([lib, vms]) => {
        if (cancelled) return;
        const names = new Set(vms.map((vm) => vm.name));
        setLibrary(lib);
        setTaken(names);
        setName(uniqueName(t("clone.defaultName", { name: source.name }), names));
      })
      .catch((err: unknown) => !cancelled && setError(asApiError(err)));
    return () => {
      cancelled = true;
    };
  }, [source.name, t]);

  // Follow the copy until it ends.
  useEffect(() => {
    if (!task || task.state !== "running") return;
    const timer = setTimeout(() => {
      api
        .task(task.id)
        .then(setTask)
        .catch((err: unknown) => setError(asApiError(err)));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [task]);

  const off = source.state === "shutoff";
  const nameValid = isValidName(name) && !taken.has(name);
  const ready: Record<Step, boolean> = {
    source: off,
    kind: true,
    name: nameValid,
    folder: library?.root != null,
    summary: true,
    copy: false,
  };
  const index = STEPS.indexOf(step);
  const target = useMemo(
    () => (library?.root ? [library.root, folder, name].filter(Boolean).join("/") : ""),
    [library, folder, name],
  );

  const start = () => {
    setError(null);
    setStep("copy");
    api
      .cloneVm(source.uuid, { kind, name, folder })
      .then(setTask)
      .catch((err: unknown) => setError(asApiError(err)));
  };

  const running = task?.state === "running" || (step === "copy" && !task && !error);
  const finished = task !== null && task.state !== "running";
  const failure =
    error ??
    (task?.state === "failed"
      ? new ApiError(0, task.error_code ?? "task.failed", task.error_detail ?? "")
      : null);

  const buttons =
    step === "copy" ? (
      finished || error ? (
        <button type="button" className="button button-primary" onClick={onClose}>
          {t("firstRun.close")}
        </button>
      ) : (
        <button
          type="button"
          className="button"
          disabled={!task}
          onClick={() => task && void api.cancelTask(task.id).then(setTask)}
        >
          {t("common.cancel")}
        </button>
      )
    ) : (
      <>
        <button type="button" className="button" onClick={onClose}>
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="button"
          disabled={index === 0}
          onClick={() => setStep(STEPS[index - 1] ?? step)}
        >
          {t("wizard.back")}
        </button>
        {step === "summary" ? (
          <button type="button" className="button button-primary" onClick={start}>
            {t("clone.start")}
          </button>
        ) : (
          <button
            type="button"
            className="button button-primary"
            disabled={!ready[step]}
            onClick={() => setStep(STEPS[index + 1] ?? step)}
          >
            {t("wizard.next")}
          </button>
        )}
      </>
    );

  return (
    <Wizard
      name={t("clone.title", { name: source.name })}
      title={t(`clone.step.${step}`)}
      step={index}
      steps={STEPS.length}
      onCancel={() => !running && onClose()}
      buttons={buttons}
    >
      {step !== "copy" && error && <ErrorMessage error={error} />}

      {step === "source" && (
        <>
          <p>{t("clone.sourceIntro", { name: source.name })}</p>
          <table className="facts">
            <tbody>
              <tr>
                <td>{t("clone.sourceVm")}</td>
                <td>{source.name}</td>
              </tr>
              <tr>
                <td>{t("clone.state")}</td>
                <td>{t(`state.${source.state}`)}</td>
              </tr>
            </tbody>
          </table>
          {!off && (
            <p className="note note-warn">
              <TriangleAlert aria-hidden />
              <span>{t("clone.mustBeOff")}</span>
            </p>
          )}
        </>
      )}

      {step === "kind" && (
        <>
          <p>{t("clone.kindIntro")}</p>
          {(["full", "linked"] as const).map((k) => (
            <div key={k}>
              <label className="check">
                <input type="radio" checked={kind === k} onChange={() => setKind(k)} />
                {t(`clone.kind.${k}`)}
              </label>
              <p className="check-hint">{t(`clone.kindHint.${k}`)}</p>
            </div>
          ))}
        </>
      )}

      {step === "name" && (
        <>
          <label className="field">
            <span>{t("clone.name")}</span>
            <input
              type="text"
              value={name}
              maxLength={64}
              autoFocus
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          {name !== "" && !isValidName(name) && (
            <p className="field-error">{t("rename.invalid")}</p>
          )}
          {taken.has(name) && <p className="field-error">{t("errors.vm.exists")}</p>}
        </>
      )}

      {step === "folder" && (
        <>
          {!library?.root && <p className="note note-error">{t("wizard.noLibrary")}</p>}
          <label className="field">
            <span>{t("clone.folder")}</span>
            <select value={folder} onChange={(e) => setFolder(e.target.value)}>
              <option value="">{t("library.myComputer")}</option>
              {(library?.folders ?? []).map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
          {target && <p className="muted mono">{target}</p>}
        </>
      )}

      {step === "summary" && (
        <>
          <table className="facts">
            <tbody>
              <tr>
                <td>{t("clone.sourceVm")}</td>
                <td>{source.name}</td>
              </tr>
              <tr>
                <td>{t("clone.kindLabel")}</td>
                <td>{t(`clone.kind.${kind}`)}</td>
              </tr>
              <tr>
                <td>{t("clone.name")}</td>
                <td>{name}</td>
              </tr>
              <tr>
                <td>{t("wizard.location")}</td>
                <td className="mono">{target}</td>
              </tr>
            </tbody>
          </table>
          <p className="muted">{t("clone.summaryHint")}</p>
          {kind === "linked" && (
            <p className="note note-warn">
              <TriangleAlert aria-hidden />
              <span>{t("clone.linkedWarning", { name: source.name })}</span>
            </p>
          )}
        </>
      )}

      {step === "copy" && (
        <>
          {failure && <ErrorMessage error={failure} />}
          {!failure && task?.state === "cancelled" && <p>{t("clone.cancelled")}</p>}
          {!failure && task?.state === "done" && (
            <>
              <p className="clone-done">
                <CircleCheck aria-hidden />
                {t("clone.done", { name })}
              </p>
              {(task.result.warnings as string[] | undefined)?.includes("state_not_copied") && (
                <p className="note note-warn">
                  <TriangleAlert aria-hidden />
                  <span>{t("clone.stateNotCopied")}</span>
                </p>
              )}
            </>
          )}
          {!failure && (!task || task.state === "running") && (
            <>
              <p>{t("clone.copying", { name })}</p>
              <div
                className="clone-progress"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((task?.progress ?? 0) * 100)}
              >
                <span style={{ width: `${(task?.progress ?? 0) * 100}%` }} />
              </div>
              <p className="muted">
                {t("clone.percent", { value: Math.round((task?.progress ?? 0) * 100) })}
                {task?.step ? ` · ${task.step}` : ""}
              </p>
            </>
          )}
        </>
      )}
    </Wizard>
  );
}

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(0, "http.error", String(err));
}
