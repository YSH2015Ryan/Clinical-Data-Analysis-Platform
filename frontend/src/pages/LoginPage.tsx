import { Button, Form, Input, message } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, setTokens, type ApiError } from "../api";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const tokens = await login(values.email, values.password);
      setTokens(tokens.access_token, tokens.refresh_token);
      navigate("/projects");
    } catch (e) {
      const err = e as ApiError;
      message.error(err.message || "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-brand">
        <p className="login-eyebrow">CLINICAL DATA ANALYSIS PLATFORM</p>
        <h1 className="login-title">
          临床数据分析平台
          <br />
          <span style={{ fontSize: "0.5em", color: "#555" }}>
            从数据上传到可投稿报告的一体化工作台
          </span>
        </h1>
        <p className="login-sub">
          为医学研究者设计：上传队列数据，自动完成质量校验、预处理、多模型比较，
          生成符合期刊规范的临床研究报告。
        </p>
        <ul className="login-points">
          <li>
            <span>质量校验</span>上传即生成列画像与问题清单，阻塞项未解决不允许进入分析
          </li>
          <li>
            <span>多模型比较</span>逻辑回归、随机森林、生存分析等 17 种模型并行计算，指标同源
          </li>
          <li>
            <span>期刊级报告</span>IMRaD 结构、结构化摘要、表图规范，HTML / PDF 一键导出
          </li>
        </ul>
      </div>
      <div className="login-form-col">
        <div className="login-card">
          <p className="login-card-title">登录</p>
          <p className="login-card-sub">使用注册邮箱进入您的研究工作台</p>
          <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
            <Form.Item
              label="邮箱"
              name="email"
              rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}
            >
              <Input autoFocus />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form>
        </div>
      </div>
    </div>
  );
}
