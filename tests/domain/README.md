# domain 测试目录说明

该目录存放纯业务规则单元测试。

重点：
- Crypto 分类先于 FDV / 500M 匹配。
- 非 500M 阈值排除。
- 等权分配和预算释放。
- `NO best ask > 0.60` 不触发买入。
- open BUY 异常触发 cancel 意图。

