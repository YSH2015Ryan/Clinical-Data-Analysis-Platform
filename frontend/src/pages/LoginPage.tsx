import { Button, Card, Form, Input, Typography, message } from "antd";
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
    <div style={{ display: "flex", justifyContent: "center", marginTop: 120 }}>
      <Card style={{ width: 380 }}>
        <Typography.Title level={3} style={{ textAlign: "center" }}>
          临床数据分析平台
        </Typography.Title>
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item
            label="邮箱"
            name="email"
            rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}
          >
            <Input autoFocus />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  );
}
