# src 目录说明

该目录存放 Python 源码包。

当前主包为 [fdv_trader](./fdv_trader/README.md)，使用 `src` layout 降低测试和本地导入时误用工作目录代码的概率。

约束：
- 源码以 Python 3.12+ 为目标。
- 业务标识使用英文，业务规则说明和关键注释可使用中文。
- 配置和密钥不得硬编码进源码。

