# tkvoice

离线语音交互服务。
唤醒词"Walker Walker"可打断当前回答

#bash package.sh              # 自增版本号
#bash package.sh 1.0.0        # 指定版本号

## 安装(必须联网，安装好后不用联网)
#拷贝到 C1

scp tkvoice_1.0.0.tar walker@新机器人IP:/debug/
cd /debug/
tar xvf tkvoice_1.0.0.tar
cd /debug/tkvoice

#安装

bash /debug/tkvoice/setup_robot.sh




