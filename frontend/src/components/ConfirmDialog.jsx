import { Modal } from './ui';

/** In-page confirmation. Used instead of window.confirm during proctored tests: native dialogs can
    knock the browser out of full screen and look like a focus loss to the proctor. */
export default function ConfirmDialog({ title, children, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger, busy, onConfirm, onCancel }) {
  return (
    <Modal title={title} onClose={onCancel}
           footer={<>
             <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
             <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
           </>}>
      <div className="small" style={{ lineHeight: 1.6 }}>{children}</div>
    </Modal>
  );
}
