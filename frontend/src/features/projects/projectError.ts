import axios from "axios";

export function projectError(error: unknown): string {
  const status = axios.isAxiosError(error) ? error.response?.status : undefined;
  if (status === 403) return "권한이 없거나 초대받은 이메일 계정과 다릅니다.";
  if (status === 404) return "프로젝트 또는 초대 코드를 찾을 수 없습니다.";
  if (status === 410) return "초대 코드가 만료되었거나 이미 사용되었습니다. 새 코드를 요청해 주세요.";
  if (status === 422) return "입력한 이름, 이메일 또는 초대 코드를 확인해 주세요.";
  return "요청을 처리하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.";
}
