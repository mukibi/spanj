#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) and accountant(mod 17) can create receipts
		if ($id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/receipts.cgi">Write Receipt</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to write a receipt.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Receipts</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/receipts.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Receipts</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/receipts.cgi">/login.html?cont=/cgi-bin/receipts.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/receipts.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}
PM: {
if ($post_mode) {
	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $paid_in_by = undef;
	#blank paid in by
	if (not exists $auth_params{"paid_in_by"} or $auth_params{"paid_in_by"} eq "") {
		$feedback = qq!<span style="color: red">You did not specify from whom this money was received.</span>!;
		$post_mode = 0;
		last PM;
	}
	else {
		$paid_in_by = $auth_params{"paid_in_by"};
	}

	my %mode_payment_lookup = ("1" => "Bank Deposit", "2" => "Cash", "3" => "Banker's Cheque", "4" => "Money Order");

	my $mode_payment = undef;
	#invalid 'mode_payment'
	if (not exists $auth_params{"mode_payment"} or $auth_params{"mode_payment"} !~ /^[1-4]$/) {
		$feedback = qq!<span style="color: red">Invalid mode of payment specified.</span>!;
		$post_mode = 0;
		last PM;
	}
	else {
		$mode_payment = $auth_params{"mode_payment"};
	}

	my $ref_id = "";

	#banker's cheques/money orders must have a ref id
	if (($mode_payment eq "3" or $mode_payment eq "4")) {
		if ( not exists $auth_params{"ref_id"} or  $auth_params{"ref_id"} eq "" ) {
			$feedback = qq!<span style="color: red">You did not specify a ref no for this ! . ( $mode_payment eq "3" ? "cheque" : "money order" ). qq!</span>!;
			$post_mode = 0;
			last PM;
		}
		else {
			$ref_id = $auth_params{"ref_id"};
		}
	}

	my $received_amount = undef;
	#invalid amount
	if (not exists $auth_params{"amount"} or $auth_params{"amount"} !~ /^\d{1,10}(\.\d{1,2})?$/) {
		$feedback = qq!<span style="color: red">Invalid amount specified.</span>!;
		$post_mode = 0;
		last PM;
	}
	else {
		$received_amount = $auth_params{"amount"};
	}

	my %accounts = ();

	my $input_votehead = undef;
	#votehead
	if ( not exists $auth_params{"votehead"} or $auth_params{"votehead"} eq "" ) {
		$feedback = qq!<span style="color: red">Invalid votehead specified.</span>!;
		$post_mode = 0;
		last PM;	
	}
	else {
		$input_votehead = lc($auth_params{"votehead"});
	}

	my $received_from = $paid_in_by;

	my $student_class = "";

	#if 'paid_in_by' is a number
	#check if there's such a student
	if ( $paid_in_by =~ /^\d+$/) {

		my $prep_stmt0 = $con->prepare("SELECT table_name FROM adms WHERE adm_no=? LIMIT 1");
	
		if ($prep_stmt0) {
			my $rc = $prep_stmt0->execute($paid_in_by);	
			if ($rc) {
				while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
					$student_class = $rslts[0];
				}
				my $prep_stmt0b = $con->prepare("SELECT s_name,o_names FROM `$student_class` WHERE adm=? LIMIT 1");
	
				if ($prep_stmt0b) {
					my $rc = $prep_stmt0b->execute($paid_in_by);	
					if ($rc) {
						while ( my @rslts = $prep_stmt0b->fetchrow_array() ) {
							$received_from = "$paid_in_by($rslts[0] $rslts[1])";	
						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM $student_class: ", $prep_stmt0b->errstr, $/;
					}
				}
				else {
					print STDERR "Couldn't prepare SELECT FROM $student_class: ", $prep_stmt0b->errstr, $/;
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt0->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt0->errstr, $/;
		}	
	}

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my $time = time;
	#write a receipt
	
	#have to calculate the hmac
	#without the receipt no
	#maybe just as well because the
	#receipt no is plaintext.
	my $hmac = uc(hmac_sha1_hex($paid_in_by . $student_class . $received_amount . $mode_payment . $ref_id . $input_votehead . $time, $key));
	my $receipt_no = undef;

	my $prep_stmt1 = $con->prepare("INSERT INTO receipts VALUES(NULL,?,?,?,?,?,?,?,?)");

	if ($prep_stmt1) {

		my $enc_paid_in_by = $cipher->encrypt(add_padding($paid_in_by));
		my $enc_class = $cipher->encrypt(add_padding($student_class));
		my $enc_amount = $cipher->encrypt(add_padding($received_amount));
		my $enc_mode_payment = $cipher->encrypt(add_padding($mode_payment));	
		my $enc_ref_id = $cipher->encrypt(add_padding($ref_id));
		my $enc_votehead = $cipher->encrypt(add_padding($input_votehead));
		my $enc_time = $cipher->encrypt(add_padding("".$time));

		my $rc = $prep_stmt1->execute($enc_paid_in_by, $enc_class, $enc_amount, $enc_mode_payment, $enc_ref_id, $enc_votehead, $enc_time, $hmac);

		if ($rc) {

			$receipt_no = $prep_stmt1->{mysql_insertid};

			my %per_votehead_assign;	
			#fees
			if ($input_votehead eq "fees") {

				my %ordered_fee_structure = ("arrears" => 0);

				#read fee structure
				my $prep_stmt2 = $con->prepare("SELECT votehead_index,votehead_name,class,amount,hmac FROM fee_structure");
	
				if ($prep_stmt2) {
	
					my $rc = $prep_stmt2->execute();
					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						
							my $decrypted_votehead_index = $cipher->decrypt($rslts[0]);
							my $decrypted_votehead_name = $cipher->decrypt($rslts[1]);
							my $decrypted_class = $cipher->decrypt($rslts[2]);
							my $decrypted_amount = $cipher->decrypt($rslts[3]);

							my $votehead_index = remove_padding($decrypted_votehead_index);
							my $votehead_name = remove_padding($decrypted_votehead_name);
							my $class = remove_padding($decrypted_class);
							my $amount = remove_padding($decrypted_amount);
	
							#valid decryption
							if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

								my $hmac = uc(hmac_sha1_hex($votehead_index . $votehead_name . $class . $amount, $key));
								
								#auth the data
								if ( $hmac eq $rslts[4] ) {	
									$ordered_fee_structure{lc($votehead_name)} = $votehead_index;
								}
							}
						}
	
						#update cash book
						#check balance
						my %enc_accounts = ();
						my @where_clause_bts = ();

						for my $votehead ( keys %ordered_fee_structure ) {

							my $enc_accnt = $cipher->encrypt(add_padding($paid_in_by . "-" . $votehead));
							$enc_accounts{$enc_accnt} = $votehead;

							push @where_clause_bts, "BINARY account_name=?";
						}
	
						my $where_clause = join(" OR ", @where_clause_bts);
	
						my $prep_stmt3 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances WHERE $where_clause");	

						if ($prep_stmt3) {
	
							my $rc = $prep_stmt3->execute(keys %enc_accounts);
							if ($rc) {

								while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
									
									my $decrypted_account_name = $cipher->decrypt($rslts[0]);
									my $decrypted_class = $cipher->decrypt($rslts[1]);
									my $decrypted_amount = $cipher->decrypt($rslts[2]);

									my $account_name = remove_padding($decrypted_account_name);
									my $class = remove_padding($decrypted_class);
									my $amount = remove_padding($decrypted_amount);

									#valid decryption
									if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

										my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

										#auth the data
										if ( $hmac eq $rslts[3] ) {
											my $votehead = $enc_accounts{$rslts[0]};
											my $votehead_index = $ordered_fee_structure{$votehead};

											$accounts{$account_name} = {"enc_account_name" => $rslts[0], "votehead" => $votehead, "votehead_index" => $votehead_index, "amount" => $amount, "class" => $class};
										}
									}

								}

								#$con->commit();
								#update account balances

								#this account already exists in
								if (scalar(keys %accounts) > 0) {

									for my $accnt (sort { ${$accounts{$a}}{"votehead_index"} <=> ${$accounts{$b}}{"votehead_index"} } keys %accounts) {

										my $votehead = 	${$accounts{$accnt}}{"votehead"};
	
										if ( ${$accounts{$accnt}}{"amount"} > 0 ) {
											#will the receipted amount clear this balance?
											if ($received_amount > ${$accounts{$accnt}}{"amount"}) {
												$received_amount -= ${$accounts{$accnt}}{"amount"};
												$per_votehead_assign{$votehead} = ${$accounts{$accnt}}{"amount"};
												${$accounts{$accnt}}{"amount"} = 0;	
											}
											else {
												${$accounts{$accnt}}{"amount"} -= $received_amount;
												$per_votehead_assign{$votehead} = $received_amount;
												$received_amount = 0;
												last;
											}
										}
									}

									#surplus becomes a -ve arrear(overpayment)
									if ( $received_amount > 0 ) {
										if (exists $accounts{$paid_in_by . "-arrears"}) {
											${$accounts{$paid_in_by . "-arrears"}}{"amount"} -= $received_amount;
											#had forgotten to add this arrears to the cash book
											$per_votehead_assign{"arrears"} = -1 * $received_amount;
										}
									}

									#update balances
									my $prep_stmt4 = $con->prepare("UPDATE account_balances SET amount=?,hmac=? WHERE BINARY account_name=?");
	
									if ( $prep_stmt4 ) {
	
										for my $accnt ( keys %accounts ) {
	
											my $enc_accnt_name = ${$accounts{$accnt}}{"enc_account_name"};
											my $hmac = uc(hmac_sha1_hex($accnt . ${$accounts{$accnt}}{"class"} . ${$accounts{$accnt}}{"amount"}, $key));
										
											my $enc_amount = $cipher->encrypt(add_padding(${$accounts{$accnt}}{"amount"}));
											my $rc = $prep_stmt4->execute($enc_amount, $hmac, $enc_accnt_name);
	
											unless ($rc) {
												print STDERR "Couldn't execute UPDATE account_balances: ", $prep_stmt4->errstr, $/;
											}
											
										}
									}
									else {
										print STDERR "Couldn't prepare UPDATE account_balances: ", $prep_stmt4->errstr, $/;
									}
								}
								#non-existent account, create an -arrears account for it with
								#all the money received
								if ( $received_amount > 0 and not exists $accounts{"$paid_in_by-arrears"} ) {

									#doing this to distinguish overpayments from a student clearing
									#their arrears
									$per_votehead_assign{"arrears"} = -1 * $received_amount;

									$accounts{"$paid_in_by-arrears"} = {"votehead" => "arrears", "votehead_index" => 0, "amount" => (-1 * $received_amount), "class" => $student_class};

									my $prep_stmt5 = $con->prepare("INSERT INTO account_balances VALUES(?,?,?,?)");

									if ($prep_stmt5) {

										my $enc_accnt_name = $cipher->encrypt(add_padding($paid_in_by . "-arrears"));
										my $enc_class = $cipher->encrypt(add_padding($student_class));
										my $enc_amount = $cipher->encrypt(add_padding($received_amount * -1));
	
										my $hmac = uc(hmac_sha1_hex($paid_in_by . "-arrears" . $student_class . (-1 * $received_amount), $key));
	
										my $rc = $prep_stmt5->execute($enc_accnt_name, $enc_class, $enc_amount, $hmac);

										unless ( $rc ) {
											print STDERR "Couldn't execute INSERT INTO account_balances: ", $prep_stmt5->errstr, $/;
										}
									}
									else {
										print STDERR "Couldn't prepare INSERT INTO account_balances: ", $prep_stmt5->errstr, $/;
									}
								}
							}
							else {
								print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt3->errstr, $/;
							}
						}
						else {
							print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt3->errstr, $/;
						}
					
					}
					else {
						print STDERR "Couldn't execute SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
					}
				}
				else {
					print STDERR "Couldn't prepare SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
				}
			}

			else {
				$per_votehead_assign{$input_votehead} = $received_amount;
			}
	
			my $enc_time = $cipher->encrypt(add_padding($time));

			my $prep_stmt6 = $con->prepare("REPLACE INTO cash_book VALUES(?,?,?,?,?)");

			if ($prep_stmt6) {

				for my $votehead ( keys %per_votehead_assign ) {

					my $enc_receipt_votehead = $cipher->encrypt(add_padding($receipt_no . "-" . $votehead));
					my $enc_votehead = $cipher->encrypt(add_padding($votehead));
					my $enc_amount = $cipher->encrypt(add_padding($per_votehead_assign{$votehead}));
				
					my $hmac = uc(hmac_sha1_hex($receipt_no . "-" . $votehead . $votehead . $per_votehead_assign{$votehead} . $time, $key));

					my $rc = $prep_stmt6->execute($enc_receipt_votehead, $enc_votehead, $enc_amount, $enc_time, $hmac);

					unless ( $rc ) {
						print STDERR "Couldn't execute INSERT INTO cash_book: ", $prep_stmt6->errstr, $/;
					}	
				}

			}
			else {
				print STDERR "Couldn't prepare INSERT INTO cash_book: ", $prep_stmt6->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't execute INSERT INTO receipts: ", $prep_stmt1->errstr, $/;
		}

	}
	else {
		print STDERR "Couldn't prepare INSERT INTO receipts: ", $prep_stmt1->errstr, $/;
	}

	#log action
	my @today = localtime;	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
       	if ($log_f) {
       		@today = localtime;	
		my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];	
		flock ($log_f, LOCK_EX) or print STDERR "Could not log write payment voucher for $id due to flock error: $!$/"; 
		seek ($log_f, 0, SEEK_END);
		print $log_f "$id WRITE RECEIPT $receipt_no($received_amount) $time\n";
		flock ($log_f, LOCK_UN);
               	close $log_f;
       	}
	else {
		print STDERR "Could not log write receipt for $id: $!\n";
	}

	$con->commit();

	my $ref_id_row = "";
	if ($ref_id ne "") {
		$ref_id_row = qq!<TR><TD style="font-weight: bold">Ref No./Code<TD>$ref_id!;
	}

	my $payment_for = uc($input_votehead);

	#amount_received has been cleared in the process of 
	#settling accounts
	my $formatted_amount = format_currency($auth_params{"amount"});
	my $new_balance_table = "";

	#show a student their
	if ( $input_votehead eq "fees" ) {

		$new_balance_table = qq!<HR><DIV style="color: white; background-color: black; font-weight: bold">Fee Balance</DIV><TABLE border="1" width="100%"><THEAD><TH>Votehead<TH>Balance</THEAD>!;

		my $total_balance = 0;

		for my $accnt ( sort { ${$accounts{$a}}{"votehead_index"} <=> ${$accounts{$b}}{"votehead_index"} } keys %accounts ) {

			
			#-ve arrears is a prepayment
			my $votehead_n = ${$accounts{$accnt}}{"votehead"};
			my $amount = ${$accounts{$accnt}}{"amount"};

			if ($votehead_n eq "arrears") {
				if ($amount < 0) {
					$votehead_n = "prepayment";
					$amount *= -1;
				}
			}
	
			my @votehead_bts = split/\s+/,$votehead_n;

			my @n_votehead_bts = ();
			foreach ( @votehead_bts ) {
				push @n_votehead_bts, ucfirst($_);
			}

			my $votehead = join(" ", @n_votehead_bts);


			$new_balance_table .= qq!<TR><TD align="left">! . $votehead . qq!<TD align="right">! . format_currency($amount);
			$total_balance += ${$accounts{$accnt}}{"amount"};
		}

		my $formatted_balance = format_currency($total_balance);

		$new_balance_table .= qq!<TR style="font-weight: bold"><TD align="left">TOTAL<TD align="right">$formatted_balance</TABLE>!;
	}

	my $f_time = sprintf "%02d/%02d/%d %02d:%02d:%02d", $today[3],$today[4]+1,$today[5]+1900,$today[2],$today[1],$today[0];	

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Receipts</title>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 10pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

}

\@media screen {
	div.noheader {}	
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div> 
<div style="height: 105mm; width: 74mm">
<img src="/images/letterhead_small.png" alt="">

<TABLE>

<TR><TD style="font-weight: bold">Receipt No.:<TD>$receipt_no
<TR><TD style="font-weight: bold">Received From:<TD>$received_from
<TR><TD style="font-weight: bold">Mode of Payment:<TD>$mode_payment_lookup{"$mode_payment"}
$ref_id_row
<TR><TD style="font-weight: bold">Payment For:<TD>$payment_for
<TR style="font-weight: bold; color: white; background-color: black"><TD>Amount:<TD>$formatted_amount
</TABLE>
$new_balance_table
<hr>
<p><span style="font-weight: bold">Received By</span>:...............................
<div style="text-align: center">$f_time</div>
</div>

</body>
</html>
*;

}
}
#display receipt book
if (not $post_mode) {
	
	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my $voteheads_select = qq!<OPTION value="fees" title="Fees" selected>Fees</OPTION>!;

	my $prep_stmt4 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM budget");
	
	if ( $prep_stmt4 ) {

		my $rc = $prep_stmt4->execute();
		my %voteheads = ();

		if ( $rc ) {

			my %votehead_hierarchy;
			my $row_cntr = 0;
			while (my @rslts = $prep_stmt4->fetchrow_array()) {	
				$voteheads{$row_cntr++} = { "votehead" => $rslts[0], "parent_votehead" => $rslts[1], "amount" => $rslts[2], "hmac" => $rslts[3] };
			}

			for my $votehead_id (keys %voteheads) {

				my $decrypted_votehead = $cipher->decrypt( $voteheads{$votehead_id}->{"votehead"} );
				my $votehead = remove_padding($decrypted_votehead);
	
				my $decrypted_votehead_parent = $cipher->decrypt( $voteheads{$votehead_id}->{"parent_votehead"});
				my $votehead_parent = remove_padding($decrypted_votehead_parent);

				my $decrypted_amnt = $cipher->decrypt( $voteheads{$votehead_id}->{"amount"});	
				my $amnt = remove_padding($decrypted_amnt);

				#valid decryption
				if ( $amnt =~ /^\-?\d+(\.\d+)?$/ ) {
					#check HMAC
					my $hmac = uc(hmac_sha1_hex($votehead . $votehead_parent . $amnt, $key));	
					if ( $hmac eq ${$voteheads{$votehead_id}}{"hmac"} ) {
						#valid entry
						#top-level votehead
						#might have been created by its 
						#children so be careful no to overwrite
						#it.
						if ( $votehead_parent eq "" ) {
							if ( not exists $votehead_hierarchy{$votehead} ) {
								$votehead_hierarchy{$votehead} = {};
							}
						}
						else {	
							${$votehead_hierarchy{$votehead_parent}}{$votehead}++;
						}
					}
				}
			}

			for my $votehead ( keys %votehead_hierarchy ) {

				my $lc_votehead = lc($votehead);

				#does this votehead have any children?
				if ( scalar(keys %{$votehead_hierarchy{$votehead}} ) > 0 ) {

					$voteheads_select .= qq!<OPTGROUP label="$votehead">!;
					$voteheads_select .= qq!<OPTION value="$lc_votehead" title="$votehead">$votehead</OPTION>!;

					for my $sub_votehead ( keys %{$votehead_hierarchy{$votehead}} ) {
						my $lc_sub_votehead = lc($sub_votehead);
						$voteheads_select .= qq!<OPTION value="$lc_sub_votehead" title="$sub_votehead">$sub_votehead</OPTION>!;
					}
					$voteheads_select .= qq!</OPTGROUP>!;
				}
				else {
					
					$voteheads_select .= qq!<OPTION value="$lc_votehead" title="$votehead">$votehead</OPTION>!;
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM budget: ", $prep_stmt4->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget: ", $prep_stmt4->errstr, $/;
	}

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq!
<\!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Receipts</title>

<script type="text/javascript">

var num_re = /^([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;
var left_padded_num = /^0+([^0]+.?\$)/;
var int_re = /^([0-9]+)/;

var httpRequest;
var url;
var cntr = 0;

var hint_adms = [];
var failed_prefices = [];

function init() {

	if (window.XMLHttpRequest) { 
		httpRequest = new XMLHttpRequest();
	}
	else if (window.ActiveXObject) {
		try {
			httpRequest = new ActiveXObject("Msxml2.XMLHTTP");
		}
		catch (e) {
			try {
				httpRequest = new ActiveXObject("Microsoft.XMLHTTP");
			}
			catch (e) {}
		}
	}

	url = window.location.protocol + '//' + window.location.hostname;	
}


function get_hints() {
	
	var search_str = document.getElementById("paid_in_by").value;

	for (var j = 0; j < failed_prefices.length; j++) {
		if (search_str.indexOf(failed_prefices[j]) == 0) {	
			return;
		}
	}

	hint_adms = [];

	if (search_str.length < 2) {
		document.getElementById("hints_list").innerHTML = "";
		document.getElementById("hints_list").style.display = "none";
		return;
	}

	var hints = "";

	if (httpRequest) {

		httpRequest.open('GET', url + '/cgi-bin/search_suggestion.cgi?q=' +  search_str, false);
		httpRequest.setRequestHeader('Content-Type', 'text/plain');
		httpRequest.setRequestHeader('Cache-Control', 'no-cache');
		httpRequest.send();
	

		
		if (httpRequest.status === 200) {
	
			var result_txt = httpRequest.responseText;

			var bts = result_txt.split("\$");

			var hints_cntr = 0;
			for (var i = 0; i < bts.length; i++) {

				var valid = bts[i].match(int_re);
				if (valid) {
					var len = bts[i].length;
					var space_subd = bts[i].replace(/ /g, "&nbsp;"); 
					hints += "<li id='" + hints_cntr + "' onmouseover='highlight(" + hints_cntr + ")' onclick='select(" + hints_cntr + ")'>" + space_subd + "</li>";

					hint_adms.push(valid[1]);
					hints_cntr++;
				}
			}
		}

		if (hints.length > 0) {

			hints = "<ul style='list-style-type: none'>" + hints + "</ul>";
			
			document.getElementById("hints_list").style.display = "block";
			document.getElementById("hints_list").style.border = "thin solid";

			if (hint_adms.length > 10) {
				document.getElementById("hints_list").style.height = "15em";
				document.getElementById("hints_list").style.overflow = "auto";
			}
			else {
				document.getElementById("hints_list").style.height = "";
			}
			document.getElementById("hints_list").innerHTML = hints;

		}
		else {
			failed_prefices.push(search_str);
			document.getElementById("hints_list").innerHTML = "";
			document.getElementById("hints_list").style.display = "none";
		}
	}
}

function highlight(adm_index) {
	for (var i = 0; i < hint_adms.length; i++) {
		if (i == adm_index) {
			document.getElementById(i + "").style.backgroundColor = '#D0D0D0';
			document.getElementById(i + "").style.cursor = "pointer";
		}
		else {
			document.getElementById(i + "").style.backgroundColor = '';
		}
	}	
}


function default_cursor() {
	document.getElementById("hints_list").style.cursor = 'auto';
}

function select(adm_index) {
	document.getElementById("paid_in_by").value = hint_adms[adm_index];
	document.getElementById("hints_list").innerHTML = "";
	document.getElementById("hints_list").style.display = "none";
}

function enable_ref_id() {
	var mode_payment = document.getElementById("mode_payment").value;
	if (mode_payment == 3 || mode_payment == 4) {
		document.getElementById("ref_id").disabled = false;
	}
	else {
		document.getElementById("ref_id").value = '';
		document.getElementById("ref_id").disabled = true;	
	}
}

function check_amount() {

	var amnt = document.getElementById("amount").value;
	var match_groups = amnt.match(num_re);

	if ( match_groups ) {
		var shs = match_groups[1];
		var cents = match_groups[3];

		var unpadded_shs = shs.match(left_padded_num);
		if (unpadded_shs) {
			shs = unpadded_shs[1];
		}

		var shs_words = "";

		var shs_digits = shs.split("");
		var last_elem = (shs_digits.length) - 1;

		var tens_words = "";
		var hundreds_words = "";
		var thousands_words = "";
		var hundred_thousand_words = "";
		var millions_words = "";
		var hundred_million_words = "";
		var billions_words = "";

		var blank_millions = true;
		var blank_thousands = true;
		var blank_tens = true;

		if (last_elem > 0) {

			var tens = (shs_digits[last_elem - 1 ] + "" + shs_digits[last_elem]);	

			if (parseInt(tens) > 0) {
				blank_tens = false;

				if (parseInt(tens) < 10) {	
					var left_padding = tens.match(left_padded_num);
					if (left_padding) {
						tens = left_padding[1];
					}
						
					tens_words = get_num_in_words_ones(tens);
				}
				else if(parseInt(tens) < 20) {				
					tens_words = get_num_in_words_teens(tens)
				}
				else {	
					var ones = get_num_in_words_ones(shs_digits[last_elem]);
					var tens = get_num_in_words_tens(shs_digits[last_elem-1]);
	
					tens_words = tens + " " + ones;
				}

			}

			if (last_elem > 1) {

				var hundreds = get_num_in_words_ones(shs_digits[last_elem-2]);
				if (hundreds.length > 0) {
					hundreds_words = hundreds + " hundred ";
				}

				if (last_elem > 2) {

					var thousands = shs_digits[last_elem - 3];

					if (last_elem > 3) {
						thousands = shs_digits[last_elem - 4] + "" + thousands;
					}

					
					//alert("thousands: " + thousands + ".");
					if (parseInt(thousands) > 0) {
						blank_thousands = false;
						if (parseInt(thousands) < 10) {
	
							var left_padding = thousands.match(left_padded_num);
							if (left_padding) {
								thousands = left_padding[1];
							}
							thousands_words = get_num_in_words_ones(thousands) + " thousand";
						}
						else if (parseInt(thousands) < 20) {	
							thousands_words = get_num_in_words_teens(thousands) + " thousand";
						}
						else if (parseInt(thousands) >= 20) {	
						
							var ones = get_num_in_words_ones(shs_digits[last_elem - 3]);
							var tens = get_num_in_words_tens(shs_digits[last_elem - 4]);
	
							thousands_words = tens + " " + ones + " thousand";	
						}

					}
					if (last_elem > 4) {	
						var hundred_thousand = get_num_in_words_ones(shs_digits[last_elem-5]);	
						if ( hundred_thousand.length > 0 ) {
							hundred_thousand_words = hundred_thousand + " hundred";
						}
					}

					if (last_elem > 5) {

						var millions = shs_digits[last_elem - 6];

						if ( last_elem > 6 ) {
							millions = shs_digits[last_elem - 7] + "" + millions;
						}

						if (parseInt(millions) > 0) {

							blank_millions = false;

							if (parseInt(millions) < 10) {					
								var left_padding = millions.match(left_padded_num);
								if (left_padding) {
									millions = left_padding[1];
								}
								millions_words = get_num_in_words_ones(millions)  + " million";
							}
							else if (parseInt(millions) < 20) {
				
								millions_words = get_num_in_words_teens(millions) + " million";
							}
							else {
					
								var ones = get_num_in_words_ones(shs_digits[last_elem - 6]);
								var tens = get_num_in_words_tens(shs_digits[last_elem - 7]);
	
								millions_words = tens + " " + ones + " million";
							}
						}
					}

					if (last_elem > 7) {
						var hundred_million = get_num_in_words_ones(shs_digits[last_elem - 8]);
						if  ( hundred_million.length > 0 ) {
							hundred_million_words = hundred_million + " hundred";
						}

						if (last_elem > 8) {
							var billions = get_num_in_words_ones(shs_digits[last_elem - 9]);
							if (billions.length > 0) {
								billions_words = billions + " billion";
							}
						}
					}
				}
			}
			var preceding_values = 0;

			if (billions_words.length > 0) {
				shs_words += billions_words;
				preceding_values++;
			}
			if (hundred_million_words.length > 0) {
				if (preceding_values) {
					shs_words += ", ";
				}

				shs_words += hundred_million_words;
				if (blank_millions) {
					shs_words += " million";
				}
				preceding_values++;
			}
			if (millions_words.length > 0) {
				if ( preceding_values && \!blank_millions ) {
					shs_words += " and ";
				}
				shs_words += millions_words;
				preceding_values++;
			}
			if ( hundred_thousand_words.length > 0 ) {
				if (preceding_values) {
					shs_words += ", ";
				}
				shs_words += hundred_thousand_words;
				if (blank_thousands) {
					shs_words += " thousand";
				}
				preceding_values++;
			}
			if (thousands_words.length > 0) {	
				if (preceding_values && \!blank_thousands) {
					shs_words += " and ";
				}
				shs_words += thousands_words;
				preceding_values++;
			}
			if (hundreds_words.length > 0) {
				if ( preceding_values) {
					shs_words += ", ";
				}
				preceding_values++;
				shs_words += hundreds_words;
			}
			if (tens_words.length > 0) {
				if (preceding_values && \!blank_tens) {
					shs_words += " and ";
				}
				shs_words += tens_words;
			}

			shs_words += " shillings";
		}
		else {
			shs_words = get_num_in_words_ones(shs_digits[0]) + " shillings";
		}
		
		var amnt_words = shs_words;	

		if (cents \!= null) {
			var unpadded_cents = cents.match(left_padded_num);
			if ( unpadded_cents ) {
				cents = unpadded_cents[1]; 
			}
			var cents_words = "";
			if (cents < 10) {
				cents_words = get_num_in_words_ones(cents);
			}
			else if (cents < 20) {
				cents_words = get_num_in_words_teens(cents);
			}
			else {	
				var cents_bts = cents.split("");

				var ones = get_num_in_words_ones(cents_bts[1]);
				var tens = get_num_in_words_tens(cents_bts[0]);
	
				cents_words = tens + " " + ones;
			}
			amnt_words += " and " + cents_words + " cents";
		}
	
		amnt_words += ".";

		var first_char = amnt_words.substr(0,1);
		var uc_first_char = first_char.toUpperCase();

		var rest_str = amnt_words.substr(1);
		amnt_words = uc_first_char + rest_str;	

		document.getElementById("amount_in_words").innerHTML = amnt_words;
		document.getElementById("amount_err").innerHTML = "";
	}
	else {
		document.getElementById("amount_err").innerHTML = "*";
		document.getElementById("amount_in_words").innerHTML = "";
	}

}

function get_num_in_words_ones(num) {
	switch (num) {
		case "0":
			return "";
		case "1":
			return "one";
		case "2":
			return "two";
		case "3":
			return "three";
		case "4":
			return "four";
		case "5":
			return "five";
		case "6":
			return "six";
		case "7":
			return "seven";
		case "8":
			return "eight";
		case "9":
			return "nine";
	}
	return "";
}

function get_num_in_words_teens(num) {
	switch (num) {
		case "10":
			return "ten";
		case "11":
			return "eleven";
		case "12":
			return "twelve";
		case "13":
			return "thirteen";
		case "14":
			return "fourteen";
		case "15":
			return "fifteen";
		case "16":
			return "sixteen";
		case "17":
			return "seventeen";
		case "18":
			return "eighteen";
		case "19":
			return "nineteen";
	}
	return "";
}

function get_num_in_words_tens(num) {
	switch (num) {	
		case "2":
			return "twenty";
		case "3":
			return "thirty";
		case "4":
			return "forty";
		case "5":
			return "fifty";
		case "6":
			return "sixty";
		case "7":
			return "seventy";
		case "8":
			return "eighty";
		case "9":
			return "ninety";
	}
	return "";
}

</script> 

</head>
<body onload="init()">
$header
$feedback
<form method="POST" action="/cgi-bin/receipts.cgi">

<input type="hidden" name="confirm_code" value="$conf_code">
<table style="text-align: left">

<tr>
<th><label for="paid_in_by">Paid in by(e.g. Adm no.)</label>
<td><input type="text" name="paid_in_by" id="paid_in_by" size="60" maxlength="31" onkeyup="get_hints()" autocomplete="off"> 
<tr><td>&nbsp;<td><span id="hints_list" style="display: none" onmouseout="default_cursor()"></span>

<tr>
<th><label for="mode_payment">Mode of Payment</label>
<td>
<select name="mode_payment" id="mode_payment" onchange="enable_ref_id()">
<option selected title="Bank Deposit" value="1">Bank Deposit</option>
<option title="Cash" value="2">Cash</option>
<option title="Banker's Cheque" value="3">Banker's Cheque</option>
<option title="Money Order" value="4">Money Order</option>
</select>

<tr style="font-style: italic">
<th><label for="ref_id">Ref no.(e.g. cheque no.)</label>
<td><input type="text" name="ref_id" disabled="1" size="20" maxlength="31" id="ref_id">

<tr>
<th><label for="amount">Amount</label>
<td><span style="color: red" id="amount_err"></span><input type="text" name="amount" id="amount" size="12" maxlength="12" onkeyup="check_amount()" onmousemove="check_amount()" autocomplete="off">

<tr style="font-style: italic">
<th>Amount in words:
<td><span id="amount_in_words"></span>

<tr>
<th>Being Payment for
<td>
<select name="votehead">
$voteheads_select
</select>

</table>
<input type="submit" name="save" value="Save">
</form>

</body>
</html>
!;

}


print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d{1,2}))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;

}
